import datetime
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from main_app.models import Attendance, AttendanceVisit, Member, TrainerAttendance, TrainerAttendanceVisit, GymProfile
from masters.models import MembershipPlan, Trainer
from .forms import AttendanceFilterForm, ManualAttendanceForm
from .models import AttendanceLog, AttendanceSummary, Occupancy
from .services import (
    annotate_attendance_duration,
    annotate_member_plan_status,
    build_member_detail_payload,
    build_trainer_detail_payload,
    get_attendance_duration_seconds,
)

GYM_MAX_CAPACITY = 100


class AttendanceManagementView(LoginRequiredMixin, View):
    """
    Single Class Based View handling the entire Attendance Management module:
    real-time statistics, filtering, searching, modal details via AJAX,
    manual check-ins/check-outs, access control alerts, and expired renewals —
    all served from one URL and one template using Bootstrap modals.
    """

    template_name = "transactions/attendance_management.html"
    login_url = "login"

    # ---------------------------------------------------------------
    # Dispatch & Routing
    # ---------------------------------------------------------------

    def get(self, request, *args, **kwargs):
        action = request.GET.get("action")
        if action == "poll_alerts":
            return self._ajax_poll_alerts(request)
        elif action == "get_member_details" or request.GET.get("ajax") == "member_details":
            return self._ajax_member_details(request)
        elif action == "get_trainer_details":
            return self._ajax_trainer_details(request)
        elif action == "manual_checkin_members":
            return self._ajax_manual_checkin_members(request)
        context = self._build_context(request)
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "check_in":
            return self._handle_check_in(request)
        elif action == "check_out":
            return self._handle_check_out(request)
        elif action == "trainer_check_in":
            return self._handle_trainer_check_in(request)
        elif action == "trainer_check_out":
            return self._handle_trainer_check_out(request)
        elif action == "renew_membership":
            return self._handle_renew(request)
        elif action == "manual_entry":
            return self._handle_manual_entry(request)

        messages.error(request, "Unknown action.")
        return redirect("attendance-management")

    # ---------------------------------------------------------------
    # AJAX Handlers
    # ---------------------------------------------------------------

    def _ajax_member_details(self, request):
        member_id = request.GET.get("member_id")
        member = get_object_or_404(Member, member_id=member_id)
        # Single source of truth for the shared Member Profile popup — the same
        # payload backs the Dashboard Membership Expiry "View cutoff" action.
        return JsonResponse(build_member_detail_payload(member))

    def _ajax_trainer_details(self, request):
        trainer_id = request.GET.get("trainer_id")
        trainer = get_object_or_404(Trainer, trainer_id=trainer_id)
        return JsonResponse(build_trainer_detail_payload(trainer))

    def _ajax_poll_alerts(self, request):
        today = timezone.localdate()
        today_all_att = Attendance.objects.filter(date=today)
        alert_keys = []
        
        member_minutes_today = {}
        for att in today_all_att.select_related("member", "member__membership_plan").filter(
            entry_time__isnull=False, status=Attendance.STATUS_INSIDE
        ):
            if not att.member: continue
            sec = get_attendance_duration_seconds(att, today)
            if sec > 0:
                member_minutes_today[att.member] = int(sec / 60)
        
        for mem, total_mins in member_minutes_today.items():
            limit_mins = 180
            if mem.membership_plan and mem.membership_plan.daily_access_hours and not mem.membership_plan.is_full_day_access:
                limit_mins = mem.membership_plan.daily_access_hours * 60
            if total_mins >= limit_mins:
                alert_keys.append(f"time_limit-{mem.member_id}")
                
        denied_alerted_members = set()
        for log in AttendanceLog.objects.filter(timestamp__date=today, entry_allowed=False).order_by("-timestamp")[:15]:
            member_id_key = log.member.member_id if log.member else f"FP: {log.fingerprint_id}"
            if member_id_key in denied_alerted_members: continue
            denied_alerted_members.add(member_id_key)
            alert_keys.append(f"denied-{log.pk}")
            
        members_inside_count = today_all_att.filter(status=Attendance.STATUS_INSIDE).values("member").distinct().count()
        gym_profile = GymProfile.get_instance()
        gym_max_capacity = gym_profile.max_occupancy if (gym_profile.max_occupancy and gym_profile.max_occupancy > 0) else 100
        if members_inside_count >= gym_max_capacity:
            alert_keys.append(f"occupancy-{members_inside_count}")
            
        return JsonResponse({"alert_keys": alert_keys})

    # ---------------------------------------------------------------
    # Action Handlers
    # ---------------------------------------------------------------

    def _ajax_manual_checkin_members(self, request):
        """
        Paginated, searchable list of subjects eligible for a Quick Check-In in
        the Manual Check-In popup — both members and trainers in one list.

        * Members: only *active* members whose membership plan is still valid
          (not expired) are ever returned — inactive members and expired
          memberships are never listed and can never be checked in from here.
        * Trainers: only *active* trainers (Permanent / Part Time) are listed;
          trainers have no membership rules, matching the biometric flow.

        Searchable by ID, Full Name, or Mobile Number. 10 rows per page across
        the combined list.
        """
        today = timezone.localdate()
        search = request.GET.get("search", "").strip()

        # ---- Eligible members ----
        member_qs = Member.objects.select_related("membership_plan").filter(
            is_active=True, membership_end_date__gte=today
        )
        if search:
            member_qs = member_qs.filter(
                Q(member_id__icontains=search)
                | Q(full_name__icontains=search)
                | Q(mobile_number__icontains=search)
            )
        member_qs = member_qs.order_by("full_name")

        # ---- Eligible trainers ----
        trainer_qs = Trainer.objects.filter(
            working_status__in=[Trainer.STATUS_PERMANENT, Trainer.STATUS_PART_TIME]
        )
        if search:
            trainer_qs = trainer_qs.filter(
                Q(trainer_id__icontains=search)
                | Q(full_name__icontains=search)
                | Q(mobile_number__icontains=search)
            )
        trainer_qs = trainer_qs.order_by("full_name")

        # Subjects already inside the gym right now (open attendance today) so
        # the UI can show a disabled "Inside" state instead of Quick Check-In.
        members_today_qs = Attendance.objects.select_related("member", "member__membership_plan").prefetch_related("visits").filter(
            date=today
        )
        members_today = {}
        for att in members_today_qs:
            last_visit = att.visits.order_by("-visit_number").first()
            entry_time = last_visit.entry_time if (last_visit and last_visit.entry_time) else att.entry_time
            
            total_seconds = get_attendance_duration_seconds(att, today)
            is_limit_reached = False
            plan = att.member.membership_plan if att.member else None
            if plan and plan.daily_access_hours and not plan.is_full_day_access:
                if total_seconds >= plan.daily_access_hours * 60 * 60:
                    is_limit_reached = True

            members_today[att.member_id] = {
                "attendance_id": att.id,
                "entry_time": entry_time.strftime("%H:%M") if entry_time else timezone.localtime().strftime("%H:%M"),
                "is_limit_reached": is_limit_reached,
                "is_inside": att.status == Attendance.STATUS_INSIDE
            }

        trainers_today_qs = TrainerAttendance.objects.prefetch_related("visits").filter(
            date=today
        )
        trainers_today = {}
        for att in trainers_today_qs:
            last_visit = att.visits.order_by("-visit_number").first()
            entry_time = last_visit.entry_time if (last_visit and last_visit.entry_time) else att.entry_time
            trainers_today[att.trainer_id] = {
                "attendance_id": att.id,
                "entry_time": entry_time.strftime("%H:%M") if entry_time else timezone.localtime().strftime("%H:%M"),
                "is_inside": att.status == TrainerAttendance.STATUS_INSIDE
            }

        rows = []
        for m in member_qs:
            att_data = members_today.get(m.pk)
            if att_data and att_data["is_limit_reached"]:
                continue
            rows.append({
                "kind": "member",
                "code": m.member_id,
                "full_name": m.full_name,
                "mobile_number": m.mobile_number,
                "detail": m.membership_plan.name if m.membership_plan else "General Plan",
                "expiry_date": m.membership_end_date.strftime("%d %b %Y") if m.membership_end_date else "--",
                "is_inside": att_data["is_inside"] if att_data else False,
                "attendance_id": att_data["attendance_id"] if att_data else None,
                "entry_time": att_data["entry_time"] if att_data else timezone.localtime().strftime("%H:%M"),
            })
        for t in trainer_qs:
            att_data = trainers_today.get(t.pk)
            rows.append({
                "kind": "trainer",
                "code": t.trainer_id,
                "full_name": t.full_name,
                "mobile_number": t.mobile_number,
                "detail": t.designation or "Trainer",
                "expiry_date": "",
                "is_inside": att_data["is_inside"] if att_data else False,
                "attendance_id": att_data["attendance_id"] if att_data else None,
                "entry_time": att_data["entry_time"] if att_data else timezone.localtime().strftime("%H:%M"),
            })

        # Members first, then trainers; alphabetical within each group.
        rows.sort(key=lambda r: (0 if r["kind"] == "member" else 1, r["full_name"].lower()))

        try:
            page_number = int(request.GET.get("page", 1))
        except (TypeError, ValueError):
            page_number = 1

        paginator = Paginator(rows, 10)
        page = paginator.get_page(page_number)

        return JsonResponse({
            "members": list(page.object_list),
            "page": page.number,
            "num_pages": paginator.num_pages,
            "total": paginator.count,
            "has_previous": page.has_previous(),
            "has_next": page.has_next(),
        })

    def _handle_check_in(self, request):
        member_id = request.POST.get("member_id")
        member = get_object_or_404(Member, member_id=member_id)
        today = timezone.localdate()
        
        entry_time_str = request.POST.get("entry_time")
        now_time = timezone.localtime().time()
        if entry_time_str:
            try:
                now_time = datetime.datetime.strptime(entry_time_str, "%H:%M").time()
            except ValueError:
                pass
                
        exit_time_str = request.POST.get("exit_time")
        exit_time = None
        if exit_time_str:
            try:
                exit_time = datetime.datetime.strptime(exit_time_str, "%H:%M").time()
            except ValueError:
                pass

        if member.is_expired or not member.is_active:
            reason = (
                "Membership expired. Access restricted."
                if member.is_expired
                else "Membership inactive. Access restricted."
            )
            AttendanceLog.objects.create(
                member=member,
                fingerprint_id=member.fingerprint_id or "UNKNOWN",
                event_type=AttendanceLog.EVENT_DENIED_EXPIRED,
                entry_allowed=False,
                reason=reason,
            )
            denial = "has expired" if member.is_expired else "is inactive"
            messages.error(request, f"ENTRY DENIED: {member.full_name}'s membership {denial}. Please renew first.")
            return redirect("attendance-management")

        att = Attendance.objects.filter(member=member, date=today).first()
        
        # Enforce Daily Access Limit for manual check-in
        if att:
            total_seconds = get_attendance_duration_seconds(att, today)
            plan = member.membership_plan
            limit_mins = 24 * 60
            if plan and plan.daily_access_hours and not plan.is_full_day_access:
                limit_mins = plan.daily_access_hours * 60
                
            if total_seconds >= limit_mins * 60:
                reason = f"Daily access limit of {limit_mins // 60} hours exceeded."
                AttendanceLog.objects.create(
                    member=member, fingerprint_id=member.fingerprint_id or "UNKNOWN",
                    event_type=AttendanceLog.EVENT_DENIED_EXPIRED,
                    entry_allowed=False, reason=reason,
                )
                messages.error(request, f"ENTRY DENIED: {member.full_name} has exceeded the {limit_mins // 60}h daily access limit.")
                return redirect("attendance-management")

        if att:
            last_visit = att.visits.order_by("-visit_number").first()
            if att.status == Attendance.STATUS_INSIDE or (last_visit and last_visit.exit_time is None):
                messages.info(request, f"{member.full_name} is currently inside the gym.")
                return redirect("attendance-management")

            next_visit_num = att.visits.count() + 1
            AttendanceVisit.objects.create(
                attendance=att,
                visit_number=next_visit_num,
                entry_time=now_time,
                exit_time=exit_time
            )
            att.status = Attendance.STATUS_CHECKED_OUT if exit_time else Attendance.STATUS_INSIDE
            if exit_time:
                att.exit_time = exit_time
            att.save()
            messages.success(request, f"Check-in recorded for {member.full_name} ({next_visit_num}nd/th Time today).")
        else:
            att = Attendance.objects.create(
                member=member,
                date=today,
                entry_time=now_time,
                exit_time=exit_time,
                status=Attendance.STATUS_CHECKED_OUT if exit_time else Attendance.STATUS_INSIDE,
                fingerprint_id=member.fingerprint_id,
                entry_allowed=True,
                membership_status_at_entry="Active",
            )
            AttendanceVisit.objects.create(
                attendance=att,
                visit_number=1,
                entry_time=now_time,
                exit_time=exit_time
            )
            messages.success(request, f"Check-in recorded for {member.full_name} (1st Time today).")

        AttendanceLog.objects.create(
            member=member,
            fingerprint_id=member.fingerprint_id or f"FP-{member.member_id}",
            event_type=AttendanceLog.EVENT_CHECKIN,
            entry_allowed=True,
            reason="Successful check-in.",
        )
        return redirect("attendance-management")

    def _handle_check_out(self, request):
        att_id = request.POST.get("attendance_id")
        att = get_object_or_404(Attendance, pk=att_id)
        
        exit_time_str = request.POST.get("exit_time")
        now_time = timezone.localtime().time()
        if exit_time_str:
            try:
                now_time = datetime.datetime.strptime(exit_time_str, "%H:%M").time()
            except ValueError:
                pass

        last_visit = att.visits.filter(exit_time__isnull=True).order_by("-visit_number").first()
        if not last_visit:
            last_visit = att.visits.order_by("-visit_number").first()

        entry_time_to_check = last_visit.entry_time if last_visit else att.entry_time
        if entry_time_to_check and now_time <= entry_time_to_check:
            messages.error(request, f"Invalid Check-out Time: Must be after the Check-in Time ({entry_time_to_check.strftime('%H:%M')}).")
            return redirect("attendance-management")

        if last_visit:
            last_visit.exit_time = now_time
            last_visit.save()
        elif att.entry_time:
            AttendanceVisit.objects.create(
                attendance=att,
                visit_number=1,
                entry_time=att.entry_time,
                exit_time=now_time
            )

        att.status = Attendance.STATUS_CHECKED_OUT
        att.exit_time = now_time
        att.save()

        AttendanceLog.objects.create(
            member=att.member,
            fingerprint_id=att.fingerprint_id or f"FP-{att.member.member_id}",
            event_type=AttendanceLog.EVENT_CHECKOUT,
            entry_allowed=True,
            reason="Check-out recorded.",
        )
        messages.info(request, f"Check-out recorded for {att.member.full_name}.")
        return redirect("attendance-management")

    def _handle_trainer_check_in(self, request):
        trainer_id = request.POST.get("trainer_id")
        trainer = get_object_or_404(Trainer, trainer_id=trainer_id)
        today = timezone.localdate()
        
        entry_time_str = request.POST.get("entry_time")
        now_time = timezone.localtime().time()
        if entry_time_str:
            try:
                now_time = datetime.datetime.strptime(entry_time_str, "%H:%M").time()
            except ValueError:
                pass
                
        exit_time_str = request.POST.get("exit_time")
        exit_time = None
        if exit_time_str:
            try:
                exit_time = datetime.datetime.strptime(exit_time_str, "%H:%M").time()
            except ValueError:
                pass

        att = TrainerAttendance.objects.filter(trainer=trainer, date=today).first()
        if att:
            last_visit = att.visits.order_by("-visit_number").first()
            if att.status == TrainerAttendance.STATUS_INSIDE or (last_visit and last_visit.exit_time is None):
                messages.info(request, f"Trainer {trainer.full_name} is currently inside the gym.")
                return redirect(f"{request.path}?tab=trainers")

            next_visit_num = att.visits.count() + 1
            TrainerAttendanceVisit.objects.create(
                attendance=att,
                visit_number=next_visit_num,
                entry_time=now_time,
                exit_time=exit_time
            )
            att.status = TrainerAttendance.STATUS_CHECKED_OUT if exit_time else TrainerAttendance.STATUS_INSIDE
            if exit_time:
                att.exit_time = exit_time
            att.save()
            messages.success(request, f"Check-in recorded for Trainer {trainer.full_name} ({next_visit_num}nd/th Time today).")
        else:
            att = TrainerAttendance.objects.create(
                trainer=trainer,
                date=today,
                entry_time=now_time,
                exit_time=exit_time,
                status=TrainerAttendance.STATUS_CHECKED_OUT if exit_time else TrainerAttendance.STATUS_INSIDE,
                fingerprint_id=getattr(trainer, "biometric_id", None) or getattr(trainer, "fingerprint_id", None),
            )
            TrainerAttendanceVisit.objects.create(
                attendance=att,
                visit_number=1,
                entry_time=now_time,
                exit_time=exit_time
            )
            messages.success(request, f"Check-in recorded for Trainer {trainer.full_name} (1st Time today).")

        return redirect(f"{request.path}?tab=trainers")

    def _handle_trainer_check_out(self, request):
        att_id = request.POST.get("attendance_id")
        att = get_object_or_404(TrainerAttendance, pk=att_id)
        
        exit_time_str = request.POST.get("exit_time")
        now_time = timezone.localtime().time()
        if exit_time_str:
            try:
                now_time = datetime.datetime.strptime(exit_time_str, "%H:%M").time()
            except ValueError:
                pass

        last_visit = att.visits.filter(exit_time__isnull=True).order_by("-visit_number").first()
        if not last_visit:
            last_visit = att.visits.order_by("-visit_number").first()

        entry_time_to_check = last_visit.entry_time if last_visit else att.entry_time
        if entry_time_to_check and now_time <= entry_time_to_check:
            messages.error(request, f"Invalid Check-out Time: Must be after the Check-in Time ({entry_time_to_check.strftime('%H:%M')}).")
            return redirect(f"{request.path}?tab=trainers")

        if last_visit:
            last_visit.exit_time = now_time
            last_visit.save()
        elif att.entry_time:
            TrainerAttendanceVisit.objects.create(
                attendance=att,
                visit_number=1,
                entry_time=att.entry_time,
                exit_time=now_time
            )

        att.status = TrainerAttendance.STATUS_CHECKED_OUT
        att.exit_time = now_time
        att.save()

        messages.info(request, f"Check-out recorded for Trainer {att.trainer.full_name}.")
        return redirect(f"{request.path}?tab=trainers")

    def _handle_renew(self, request):
        member_id = request.POST.get("member_id")
        member = get_object_or_404(Member, member_id=member_id)
        today = timezone.localdate()
        duration_days = 365
        if member.membership_plan and member.membership_plan.duration:
            if member.membership_plan.duration_type == MembershipPlan.DURATION_MONTHS:
                duration_days = member.membership_plan.duration * 30
            elif member.membership_plan.duration_type == MembershipPlan.DURATION_YEARS:
                duration_days = member.membership_plan.duration * 365
            elif member.membership_plan.duration_type == MembershipPlan.DURATION_WEEKS:
                duration_days = member.membership_plan.duration * 7
            else:
                duration_days = member.membership_plan.duration

        member.membership_start_date = today
        member.membership_end_date = today + timedelta(days=duration_days)
        member.is_active = True
        member.save()

        messages.success(request, f"Membership renewed successfully for {member.full_name}!")
        return redirect("attendance-management")

    def _handle_manual_entry(self, request):
        form = ManualAttendanceForm(request.POST)
        if form.is_valid():
            new_att = form.save(commit=False)
            existing_att = Attendance.objects.filter(member=new_att.member, date=new_att.date).first()
            if existing_att:
                next_num = existing_att.visits.count() + 1
                AttendanceVisit.objects.create(
                    attendance=existing_att,
                    visit_number=next_num,
                    entry_time=new_att.entry_time,
                    exit_time=new_att.exit_time
                )
                if new_att.status:
                    existing_att.status = new_att.status
                if new_att.exit_time:
                    existing_att.exit_time = new_att.exit_time
                elif new_att.entry_time and not existing_att.entry_time:
                    existing_att.entry_time = new_att.entry_time
                existing_att.save()
                messages.success(request, f"Manual visit #{next_num} added to {new_att.member.full_name}'s daily attendance.")
            else:
                if not new_att.fingerprint_id and new_att.member:
                    new_att.fingerprint_id = new_att.member.fingerprint_id or f"MANUAL-{new_att.member.member_id}"
                new_att.save()
                AttendanceVisit.objects.create(
                    attendance=new_att,
                    visit_number=1,
                    entry_time=new_att.entry_time,
                    exit_time=new_att.exit_time
                )
                messages.success(request, "Manual attendance entry saved successfully.")
        else:
            messages.error(request, "Failed to save manual entry. Please check the form fields.")
        return redirect("attendance-management")

    # ---------------------------------------------------------------
    # Context Builder
    # ---------------------------------------------------------------

    def _build_context(self, request):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        # Filters
        filter_date_str = request.GET.get("date", str(today))
        try:
            query_date = datetime.date.fromisoformat(filter_date_str)
        except ValueError:
            query_date = today

        search_query = request.GET.get("search", "").strip()
        status_filter = request.GET.get("status", "all")

        # Query Attendance records for selected date
        attendance_qs = Attendance.objects.select_related("member", "member__membership_plan").filter(date=query_date)

        # Change 6 — Member Attendance Records must list only members who are
        # currently Active AND hold an Active Membership Plan (an assigned,
        # active plan whose membership window has not expired). This applies
        # ONLY to member records; trainer records below are unaffected.
        attendance_qs = attendance_qs.filter(
            member__is_active=True,
            member__membership_plan__isnull=False,
            member__membership_end_date__gte=today,
        )

        if search_query:
            attendance_qs = attendance_qs.filter(
                Q(member__full_name__icontains=search_query)
                | Q(member__member_id__icontains=search_query)
                | Q(fingerprint_id__icontains=search_query)
            )

        if status_filter == "inside":
            attendance_qs = attendance_qs.filter(status=Attendance.STATUS_INSIDE)
        elif status_filter == "checked_out":
            attendance_qs = attendance_qs.filter(status=Attendance.STATUS_CHECKED_OUT)
        elif status_filter == "expired":
            attendance_qs = attendance_qs.filter(status=Attendance.STATUS_EXPIRED)

        # ---- Statistics Cards (always computed for Today to keep dashboard live) ----
        today_all_att = Attendance.objects.filter(date=today)
        yesterday_all_att = Attendance.objects.filter(date=yesterday)

        # Count unique members only for Today's Attendance summary per Multiple Entry Logic requirement
        today_attendance_count = today_all_att.values("member").distinct().count()
        yesterday_attendance_count = yesterday_all_att.values("member").distinct().count()
        attendance_growth = 0
        if yesterday_attendance_count > 0:
            attendance_growth = round(((today_attendance_count - yesterday_attendance_count) / yesterday_attendance_count) * 100)
        elif today_attendance_count > 0:
            attendance_growth = 100

        members_inside_count = today_all_att.filter(status=Attendance.STATUS_INSIDE).values("member").distinct().count()
        today_checkins_count = today_all_att.count()  # Total physical entries recorded
        today_checkouts_count = today_all_att.filter(status=Attendance.STATUS_CHECKED_OUT).count()

        total_members = Member.objects.count()
        active_memberships_count = Member.objects.filter(is_active=True, membership_end_date__gte=today).count()
        expired_memberships_count = Member.objects.filter(membership_end_date__lt=today).count()
        # Count only trainers who are physically inside the gym right now
        # (an open TrainerAttendance record for today), NOT the total number
        # of registered/active trainers. A trainer is "inside" when their
        # latest attendance record for today is still in the INSIDE state.
        trainers_inside_count = (
            TrainerAttendance.objects.filter(
                date=today, status=TrainerAttendance.STATUS_INSIDE
            )
            .values("trainer")
            .distinct()
            .count()
        )

        attendance_rate = 0
        if active_memberships_count > 0:
            attendance_rate = round((today_attendance_count / active_memberships_count) * 100)

        gym_profile = GymProfile.get_instance()
        gym_max_capacity = gym_profile.max_occupancy if (gym_profile.max_occupancy and gym_profile.max_occupancy > 0) else 100
        occupancy_percentage = 0
        if gym_max_capacity > 0:
            occupancy_percentage = round((members_inside_count / gym_max_capacity) * 100, 1)

        active_tab = request.GET.get("tab", "members")

        # ---- Annotate & Sort Attendance Records for Table Display ----
        raw_att_list = list(attendance_qs.prefetch_related("visits").order_by("-date", "-entry_time", "-id"))
        grouped_att = {}
        for att in raw_att_list:
            key = (att.member_id, att.date)
            if key not in grouped_att:
                grouped_att[key] = []
            grouped_att[key].append(att)

        dedup_att_list = []
        for key, group in grouped_att.items():
            primary_att = group[0]
            all_visits = []
            for att in group:
                vs = list(att.visits.all())
                if not vs and att.entry_time:
                    vs = [AttendanceVisit(attendance=att, visit_number=1, entry_time=att.entry_time, exit_time=att.exit_time)]
                all_visits.extend(vs)

            if len(group) > 1:
                for v in all_visits:
                    if v.pk and v.attendance_id != primary_att.pk:
                        v.attendance = primary_att
                        v.save()
                    elif not v.pk:
                        v.attendance = primary_att
                        v.save()
                for dup in group[1:]:
                    dup.delete()

            all_visits.sort(key=lambda v: (v.entry_time or datetime.time.min, v.visit_number))
            for idx, v in enumerate(all_visits, start=1):
                if v.visit_number != idx:
                    v.visit_number = idx
                    if v.pk:
                        v.save()

            primary_att.visit_list = all_visits
            primary_att.visits_count = len(all_visits)
            if len(all_visits) <= 1:
                primary_att.visit_label = ""
            elif len(all_visits) == 2:
                primary_att.visit_label = "2nd Time"
            elif len(all_visits) == 3:
                primary_att.visit_label = "3rd Time"
            else:
                primary_att.visit_label = f"{len(all_visits)}th Time"

            if all_visits:
                primary_att.entry_time = all_visits[0].entry_time or primary_att.entry_time
                primary_att.exit_time = all_visits[-1].exit_time if all(v.exit_time is not None for v in all_visits) else None
                new_status = Attendance.STATUS_INSIDE if any(v.exit_time is None for v in all_visits) else Attendance.STATUS_CHECKED_OUT
                if primary_att.status != new_status:
                    primary_att.status = new_status
                    primary_att.save()

            dedup_att_list.append(primary_att)

        raw_att_list = dedup_att_list
        for att in raw_att_list:
            # Duration badge + membership status badges are rendered identically
            # here and on the Dashboard's Recent Attendance widget — the shared
            # service functions in transactions.services are the single source of
            # truth so the two views can never drift.
            annotate_attendance_duration(att, today)
            annotate_member_plan_status(att, today)

            # Bug 1 fix — derive is_limit_reached directly from the
            # total_day_minutes already computed by annotate_attendance_duration
            # above so that the duration-badge colour and the check-in button
            # disabled state are ALWAYS in sync (single computation path).
            att.is_limit_reached = False
            if att.member:
                plan = att.member.membership_plan
                if plan and plan.daily_access_hours and not plan.is_full_day_access:
                    limit_mins = plan.daily_access_hours * 60
                    total_mins = getattr(att, 'total_day_minutes', 0)
                    if total_mins >= limit_mins:
                        att.is_limit_reached = True

        if status_filter == "all" and query_date == today:
            checked_member_ids = {att.member_id for att in raw_att_list if att.member_id}
            for m in Member.objects.filter(is_active=True, membership_end_date__gte=today):
                if m.id not in checked_member_ids:
                    if search_query and search_query.lower() not in m.full_name.lower() and search_query.lower() not in m.member_id.lower() and search_query.lower() not in (m.fingerprint_id or "").lower():
                        continue
                    dummy_att = Attendance(member=m, date=today, status="not_checked_in", fingerprint_id=m.fingerprint_id)
                    dummy_att.visit_list = []
                    dummy_att.visits_count = 0
                    dummy_att.total_day_duration_str = "--"
                    if m.membership_end_date:
                        days_rem = (m.membership_end_date - today).days
                        dummy_att.plan_expiry_str = m.membership_end_date.strftime("%d %b %Y")
                        if days_rem < 0 or not m.is_active:
                            dummy_att.status_text = "Expired Plan"
                            dummy_att.badge_class = "bg-danger text-white"
                            dummy_att.status_icon = "bi-x-circle-fill"
                        elif days_rem <= 10:
                            day_word = "day" if days_rem == 1 else "days"
                            dummy_att.status_text = f"Expires in {days_rem} {day_word}"
                            dummy_att.badge_class = "bg-warning text-dark"
                            dummy_att.status_icon = "bi-exclamation-triangle-fill"
                        else:
                            dummy_att.status_text = "Active Plan"
                            dummy_att.badge_class = "bg-success text-white"
                            dummy_att.status_icon = "bi-check-circle-fill"
                    else:
                        dummy_att.plan_expiry_str = "--"
                        dummy_att.status_text = "Active Plan"
                        dummy_att.badge_class = "bg-success text-white"
                        dummy_att.status_icon = "bi-check-circle-fill"
                    dummy_att.is_not_checked_in = True
                    dummy_att.is_limit_reached = False
                    raw_att_list.append(dummy_att)

        # ---- Annotate & Sort Trainer Attendance Records ----
        trainer_attendance_qs = TrainerAttendance.objects.select_related("trainer").prefetch_related("visits").filter(date=query_date)
        if search_query:
            trainer_attendance_qs = trainer_attendance_qs.filter(
                Q(trainer__full_name__icontains=search_query)
                | Q(trainer__trainer_id__icontains=search_query)
                | Q(fingerprint_id__icontains=search_query)
            )
        if status_filter == "inside":
            trainer_attendance_qs = trainer_attendance_qs.filter(status=TrainerAttendance.STATUS_INSIDE)
        elif status_filter == "checked_out":
            trainer_attendance_qs = trainer_attendance_qs.filter(status=TrainerAttendance.STATUS_CHECKED_OUT)

        trainer_att_list = list(trainer_attendance_qs.order_by("-date", "-entry_time", "-id"))
        checked_trainer_ids = set()
        for t_att in trainer_att_list:
            checked_trainer_ids.add(t_att.trainer_id)
            visits = list(t_att.visits.all())
            if not visits and t_att.entry_time:
                visits = [TrainerAttendanceVisit(attendance=t_att, visit_number=1, entry_time=t_att.entry_time, exit_time=t_att.exit_time)]
            visits.sort(key=lambda v: v.visit_number)
            t_att.visit_list = visits
            t_att.visits_count = len(visits)
            if len(visits) <= 1:
                t_att.visit_label = ""
            elif len(visits) == 2:
                t_att.visit_label = "2nd Time"
            elif len(visits) == 3:
                t_att.visit_label = "3rd Time"
            else:
                t_att.visit_label = f"{len(visits)}th Time"

            total_seconds = 0
            if visits:
                for v in visits:
                    if v.entry_time and v.exit_time:
                        entry_dt = timezone.datetime.combine(t_att.date, v.entry_time)
                        exit_dt = timezone.datetime.combine(t_att.date, v.exit_time)
                        sec = (exit_dt - entry_dt).total_seconds()
                        if sec > 0:
                            total_seconds += sec
                    elif v.entry_time and not v.exit_time:
                        if t_att.date == today:
                            entry_dt = timezone.datetime.combine(t_att.date, v.entry_time)
                            now_dt = timezone.datetime.combine(today, timezone.localtime().time())
                            sec = (now_dt - entry_dt).total_seconds()
                            if sec > 0:
                                total_seconds += sec
            else:
                if t_att.entry_time and t_att.exit_time:
                    entry_dt = timezone.datetime.combine(t_att.date, t_att.entry_time)
                    exit_dt = timezone.datetime.combine(t_att.date, t_att.exit_time)
                    sec = (exit_dt - entry_dt).total_seconds()
                    if sec > 0:
                        total_seconds += sec
                elif t_att.entry_time and not t_att.exit_time and t_att.date == today:
                    entry_dt = timezone.datetime.combine(t_att.date, t_att.entry_time)
                    now_dt = timezone.datetime.combine(today, timezone.localtime().time())
                    sec = (now_dt - entry_dt).total_seconds()
                    if sec > 0:
                        total_seconds += sec

            if total_seconds > 0:
                hours, remainder = divmod(int(total_seconds), 3600)
                minutes, _ = divmod(remainder, 60)
                if hours > 0 and minutes > 0:
                    t_att.total_day_duration_str = f"{hours}h {minutes}m"
                elif hours > 0:
                    t_att.total_day_duration_str = f"{hours}h 00m"
                else:
                    t_att.total_day_duration_str = f"{max(1, minutes)}m"
            else:
                t_att.total_day_duration_str = "--"

        if status_filter == "all" and query_date == today:
            for trn in Trainer.objects.filter(
                working_status__in=[Trainer.STATUS_PERMANENT, Trainer.STATUS_PART_TIME]
            ):
                if trn.id not in checked_trainer_ids:
                    if search_query and search_query.lower() not in trn.full_name.lower() and search_query.lower() not in trn.trainer_id.lower():
                        continue
                    # Create dummy unsaved record for display
                    dummy_t_att = TrainerAttendance(trainer=trn, date=today, status="not_checked_in")
                    dummy_t_att.visit_list = []
                    dummy_t_att.visits_count = 0
                    dummy_t_att.total_day_duration_str = "--"
                    dummy_t_att.is_not_checked_in = True
                    trainer_att_list.append(dummy_t_att)

        # ---- Notifications / Alerts ----
        # Two structured alert types drive the Access Control & Security panel:
        #   * occupancy_alert — a single banner when the gym is at/over capacity
        #   * alerts (time-limit) — one banner per member who has exceeded their
        #     plan's daily access limit, with the data shown in each row
        #     (avatar, daily limit, check-in time, live time inside).
        occupancy_alert = None
        if members_inside_count >= gym_max_capacity:
            occupancy_alert = {
                "inside": members_inside_count,
                "capacity": gym_max_capacity,
                "over_by": max(0, members_inside_count - gym_max_capacity),
                "occupancy_percentage": occupancy_percentage,
            }

        alerts = []
        alerted_member_ids = set()
        member_minutes_today = {}
        member_first_entry = {}
        now_dt = timezone.localtime()
        for att in today_all_att.select_related("member", "member__membership_plan").filter(
            entry_time__isnull=False, status=Attendance.STATUS_INSIDE
        ):
            if not att.member:
                continue
            
            # Use the consistent, visit-aware calculation
            sec = get_attendance_duration_seconds(att, today)
            
            if sec > 0:
                member_minutes_today[att.member] = int(sec / 60)
                
            # Track the earliest check-in of the day for display (this is fine as it relies on the first entry_time).
            if (att.member not in member_first_entry) or (att.entry_time and att.entry_time < member_first_entry[att.member]):
                member_first_entry[att.member] = att.entry_time

        for mem, total_mins in member_minutes_today.items():
            if mem.member_id in alerted_member_ids:
                continue
            limit_mins = 180
            if mem.membership_plan and mem.membership_plan.daily_access_hours and not mem.membership_plan.is_full_day_access:
                limit_mins = mem.membership_plan.daily_access_hours * 60
            if total_mins >= limit_mins:
                alerted_member_ids.add(mem.member_id)
                h, m = divmod(total_mins, 60)
                lh, lm = divmod(limit_mins, 60)
                daily_limit_str = f"{lh}h" if lm == 0 else f"{lh}h {lm}m"
                entry_t = member_first_entry.get(mem)
                photo_url = mem.photo.url if mem.photo else (
                    f"https://ui-avatars.com/api/?name={mem.full_name}&background=2E6DA4&color=fff&size=96"
                )
                alerts.append({
                    "id": mem.member_id,
                    "name": mem.full_name,
                    "type": "time_limit",
                    "title": "Time Limit Exceeded",
                    "photo_url": photo_url,
                    "daily_limit": daily_limit_str,
                    "checkin_time": entry_t.strftime("%I:%M %p").lstrip("0") if entry_t else "--",
                    "time_inside": f"{h}h {m}m",
                    "message": f"{mem.full_name} has exceeded the {daily_limit_str} daily access limit.",
                })

        # Access Denied logs today (kept as time-limit-styled security alerts)
        denied_alerted_members = set()
        for log in AttendanceLog.objects.filter(timestamp__date=today, entry_allowed=False).order_by("-timestamp")[:15]:
            member_id_key = log.member.member_id if log.member else f"FP: {log.fingerprint_id}"
            if member_id_key in denied_alerted_members:
                continue
            denied_alerted_members.add(member_id_key)
            
            name = log.member.full_name if log.member else f"FP: {log.fingerprint_id}"
            photo_url = (
                log.member.photo.url if (log.member and log.member.photo)
                else f"https://ui-avatars.com/api/?name={name}&background=C4361D&color=fff&size=96"
            )
            alerts.append({
                "id": log.member.member_id if log.member else "",
                "name": name,
                "type": "denied",
                "title": "Access Denied",
                "photo_url": photo_url,
                "daily_limit": "",
                "checkin_time": log.timestamp.strftime("%I:%M %p").lstrip("0"),
                "time_inside": "",
                "message": f"Turnstile entry restricted for {name} ({log.reason}).",
                # Change 7 — stable per-alert key so a dismissed Access Denied
                # alert stays dismissed across page refreshes (persisted client
                # side in localStorage; no DB schema change).
                "dismiss_key": f"denied-{log.pk}",
            })
            if len(denied_alerted_members) >= 3:
                break

        # ---- Expired Memberships List ----
        expired_members = Member.objects.select_related("membership_plan").filter(membership_end_date__lt=today).order_by("membership_end_date")
        expired_list = []
        for em in expired_members:
            days_exp = (today - em.membership_end_date).days
            expired_list.append({
                "id": em.member_id,
                "name": em.full_name,
                "photo_url": em.photo.url if (em.photo and em.photo.name) else f"https://ui-avatars.com/api/?name={em.full_name}&background=random&size=64",
                "plan": em.membership_plan.name if em.membership_plan else "General Plan",
                "expiry_date": em.membership_end_date.strftime("%d-%b-%Y"),
                "days_expired": days_exp,
            })

        # Forms
        filter_form = AttendanceFilterForm(initial={
            "date": query_date.strftime("%Y-%m-%d"),
            "search": search_query,
            "status": status_filter,
        })
        page_num = request.GET.get("page", 1)
        paginator_members = Paginator(raw_att_list, 10)
        attendance_records_page = paginator_members.get_page(page_num)

        paginator_trainers = Paginator(trainer_att_list, 10)
        trainer_attendance_records_page = paginator_trainers.get_page(page_num)

        return {
            "attendance_records": attendance_records_page,
            "trainer_attendance_records": trainer_attendance_records_page,
            "page_obj": trainer_attendance_records_page if active_tab == "trainers" else attendance_records_page,
            "active_tab": active_tab,
            "query_date": query_date,
            "today": today,
            "filter_form": filter_form,
            # Statistics
            "today_attendance_count": today_attendance_count,
            "attendance_growth": attendance_growth,
            "members_inside_count": members_inside_count,
            "trainers_inside_count": trainers_inside_count,
            "attendance_rate": attendance_rate,
            "active_memberships_count": active_memberships_count,
            "expired_memberships_count": expired_memberships_count,
            "today_checkins_count": today_checkins_count,
            "today_checkouts_count": today_checkouts_count,
            "occupancy_percentage": occupancy_percentage,
            "gym_max_capacity": gym_max_capacity,
            # Alerts & Expired
            "alerts": alerts,
            "occupancy_alert": occupancy_alert,
            "expired_members": expired_list,
            "expired_count": len(expired_list),
        }


