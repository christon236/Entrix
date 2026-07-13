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

from main_app.models import Attendance, AttendanceVisit, Member, TrainerAttendance, TrainerAttendanceVisit
from masters.models import MembershipPlan, Trainer
from .forms import AttendanceFilterForm, ManualAttendanceForm
from .models import AttendanceLog, AttendanceSummary, Occupancy

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
        if action == "get_member_details" or request.GET.get("ajax") == "member_details":
            return self._ajax_member_details(request)
        elif action == "get_trainer_details":
            return self._ajax_trainer_details(request)
        self._ensure_sample_data()
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

        # Calculate BMI
        bmi_str = "--"
        try:
            h_m = float(member.height.replace("cm", "").strip()) / 100.0
            w_kg = float(member.weight.replace("kg", "").strip())
            if h_m > 0:
                bmi_str = f"{w_kg / (h_m * h_m):.1f}"
        except (ValueError, ZeroDivisionError, AttributeError):
            bmi_str = "23.5"  # Fallback clean default

        # Calculate Joined Since
        now = timezone.now().date()
        days_joined = max(1, (now - member.join_date).days)
        if days_joined < 30:
            joined_since = f"{days_joined} Days"
        elif days_joined < 365:
            months = days_joined // 30
            joined_since = f"{months} Month{'s' if months > 1 else ''}"
        else:
            years = days_joined // 365
            months = (days_joined % 365) // 30
            joined_since = f"{years} Year{'s' if years > 1 else ''}"
            if months > 0:
                joined_since += f" {months} Month{'s' if months > 1 else ''}"

        # Attendance Summary stats
        today = timezone.localdate()
        today_att = Attendance.objects.filter(member=member, date=today).first()
        checkin_today = today_att.entry_time.strftime("%I:%M %p") if (today_att and today_att.entry_time) else "--"
        duration_inside = today_att.duration if today_att else "Left"
        if today_att and today_att.status == Attendance.STATUS_INSIDE and today_att.entry_time:
            # Live duration calculation
            now_time = timezone.localtime().time()
            dt_now = datetime.datetime.combine(today, now_time)
            dt_entry = datetime.datetime.combine(today, today_att.entry_time)
            mins = int((dt_now - dt_entry).total_seconds() / 60)
            h, m = divmod(max(0, mins), 60)
            duration_inside = f"{h}h {m}m" if h > 0 else f"{m} min"

        month_start = today.replace(day=1)
        month_visits = Attendance.objects.filter(member=member, date__gte=month_start).count()
        total_visits = Attendance.objects.filter(member=member).count()
        last_visit_obj = Attendance.objects.filter(member=member).order_by("-date", "-entry_time").first()
        last_visit = last_visit_obj.date.strftime("%Y-%m-%d") if last_visit_obj else member.join_date.strftime("%Y-%m-%d")

        photo_url = member.photo.url if member.photo else f"https://ui-avatars.com/api/?name={member.full_name}&background=random&size=128"

        data = {
            "id": member.member_id,
            "name": member.full_name,
            "photo_url": photo_url,
            "status": "Active" if not member.is_expired else "Expired",
            "gender": member.get_gender_display() or "Male",
            "blood_group": member.blood_group or "O+",
            "mobile": member.mobile_number,
            "join_date": member.join_date.strftime("%Y-%m-%d"),
            "expiry_date": member.membership_end_date.strftime("%d-%b-%Y") if member.membership_end_date else "--",
            "height": member.height or "175 cm",
            "weight": member.weight or "75 kg",
            "bmi": bmi_str,
            "fitness_goal": member.fitness_goal or "General Fitness",
            "medical_condition": member.medical_condition or "None",
            "plan": member.membership_plan.name if member.membership_plan else "General Plan",
            "joined_since": joined_since,
            "total_visits": total_visits,
            "last_visit": last_visit,
            "checkin_today": checkin_today,
            "duration_inside": duration_inside,
            "month_visits": f"{month_visits} visits",
            "total_attendance": f"{total_visits} visits",
        }
        return JsonResponse(data)

    def _ajax_trainer_details(self, request):
        trainer_id = request.GET.get("trainer_id")
        trainer = get_object_or_404(Trainer, trainer_id=trainer_id)
        today = timezone.localdate()

        att = TrainerAttendance.objects.filter(trainer=trainer, date=today).first()
        checkin_today = "Yes" if att else "No"
        duration_inside = "--"
        if att and att.status == TrainerAttendance.STATUS_INSIDE and att.entry_time:
            now_time = timezone.localtime().time()
            dt_now = datetime.datetime.combine(today, now_time)
            dt_entry = datetime.datetime.combine(today, att.entry_time)
            mins = int((dt_now - dt_entry).total_seconds() / 60)
            h, m = divmod(max(0, mins), 60)
            duration_inside = f"{h}h {m}m" if h > 0 else f"{m} min"

        month_start = today.replace(day=1)
        month_visits = TrainerAttendance.objects.filter(trainer=trainer, date__gte=month_start).count()
        total_visits = TrainerAttendance.objects.filter(trainer=trainer).count()
        last_visit_obj = TrainerAttendance.objects.filter(trainer=trainer).order_by("-date", "-entry_time").first()
        last_visit = last_visit_obj.date.strftime("%Y-%m-%d") if last_visit_obj else trainer.joining_date.strftime("%Y-%m-%d")

        photo_url = trainer.photo.url if trainer.photo else f"https://ui-avatars.com/api/?name={trainer.full_name}&background=random&size=128"

        data = {
            "id": trainer.trainer_id,
            "name": trainer.full_name,
            "photo_url": photo_url,
            "status": trainer.working_status,
            "gender": trainer.get_gender_display() or "Male",
            "blood_group": "O+",
            "mobile": trainer.mobile_number,
            "join_date": trainer.joining_date.strftime("%Y-%m-%d"),
            "expiry_date": "N/A (Staff)",
            "height": "--",
            "weight": "--",
            "bmi": "--",
            "fitness_goal": trainer.get_designation_display(),
            "medical_condition": "None",
            "plan": f"Trainer - {trainer.get_designation_display()}",
            "joined_since": f"Since {trainer.joining_date.strftime('%b %Y')}",
            "total_visits": total_visits,
            "last_visit": last_visit,
            "checkin_today": checkin_today,
            "duration_inside": duration_inside,
            "month_visits": f"{month_visits} days",
            "total_attendance": f"{total_visits} days",
        }
        return JsonResponse(data)

    # ---------------------------------------------------------------
    # Action Handlers
    # ---------------------------------------------------------------

    def _handle_check_in(self, request):
        member_id = request.POST.get("member_id")
        member = get_object_or_404(Member, member_id=member_id)
        today = timezone.localdate()
        now_time = timezone.localtime().time()

        if member.is_expired:
            AttendanceLog.objects.create(
                member=member,
                fingerprint_id=member.fingerprint_id or "UNKNOWN",
                event_type=AttendanceLog.EVENT_DENIED_EXPIRED,
                entry_allowed=False,
                reason="Membership expired. Access restricted.",
            )
            messages.error(request, f"ENTRY DENIED: {member.full_name}'s membership has expired. Please renew first.")
            return redirect("attendance-management")

        att = Attendance.objects.filter(member=member, date=today).first()
        if att:
            last_visit = att.visits.order_by("-visit_number").first()
            if att.status == Attendance.STATUS_INSIDE or (last_visit and last_visit.exit_time is None):
                messages.info(request, f"{member.full_name} is currently inside the gym.")
                return redirect("attendance-management")

            next_visit_num = att.visits.count() + 1
            AttendanceVisit.objects.create(
                attendance=att,
                visit_number=next_visit_num,
                entry_time=now_time
            )
            att.status = Attendance.STATUS_INSIDE
            att.save()
            messages.success(request, f"Check-in recorded for {member.full_name} ({next_visit_num}nd/th Time today).")
        else:
            att = Attendance.objects.create(
                member=member,
                date=today,
                entry_time=now_time,
                status=Attendance.STATUS_INSIDE,
                fingerprint_id=member.fingerprint_id,
                entry_allowed=True,
                membership_status_at_entry="Active",
            )
            AttendanceVisit.objects.create(
                attendance=att,
                visit_number=1,
                entry_time=now_time
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
        now_time = timezone.localtime().time()

        last_visit = att.visits.filter(exit_time__isnull=True).order_by("-visit_number").first()
        if not last_visit:
            last_visit = att.visits.order_by("-visit_number").first()

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
        now_time = timezone.localtime().time()

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
                entry_time=now_time
            )
            att.status = TrainerAttendance.STATUS_INSIDE
            att.save()
            messages.success(request, f"Check-in recorded for Trainer {trainer.full_name} ({next_visit_num}nd/th Time today).")
        else:
            att = TrainerAttendance.objects.create(
                trainer=trainer,
                date=today,
                entry_time=now_time,
                status=TrainerAttendance.STATUS_INSIDE,
                fingerprint_id=trainer.fingerprint_id,
            )
            TrainerAttendanceVisit.objects.create(
                attendance=att,
                visit_number=1,
                entry_time=now_time
            )
            messages.success(request, f"Check-in recorded for Trainer {trainer.full_name} (1st Time today).")

        return redirect(f"{request.path}?tab=trainers")

    def _handle_trainer_check_out(self, request):
        att_id = request.POST.get("attendance_id")
        att = get_object_or_404(TrainerAttendance, pk=att_id)
        now_time = timezone.localtime().time()

        last_visit = att.visits.filter(exit_time__isnull=True).order_by("-visit_number").first()
        if not last_visit:
            last_visit = att.visits.order_by("-visit_number").first()

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
        trainers_inside_count = Trainer.objects.filter(working_status=Trainer.STATUS_WORKING).count()

        attendance_rate = 0
        if active_memberships_count > 0:
            attendance_rate = round((today_attendance_count / active_memberships_count) * 100)

        occupancy_percentage = 0
        if GYM_MAX_CAPACITY > 0:
            occupancy_percentage = round((members_inside_count / GYM_MAX_CAPACITY) * 100, 1)

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
            visits = att.visit_list

            # Calculate total duration for the entire day across all visits
            total_seconds = 0
            if visits:
                for v in visits:
                    if v.entry_time and v.exit_time:
                        entry_dt = timezone.datetime.combine(att.date, v.entry_time)
                        exit_dt = timezone.datetime.combine(att.date, v.exit_time)
                        sec = (exit_dt - entry_dt).total_seconds()
                        if sec > 0:
                            total_seconds += sec
                    elif v.entry_time and not v.exit_time:
                        if att.date == today:
                            entry_dt = timezone.datetime.combine(att.date, v.entry_time)
                            now_dt = timezone.datetime.combine(today, timezone.localtime().time())
                            sec = (now_dt - entry_dt).total_seconds()
                            if sec > 0:
                                total_seconds += sec
            else:
                if att.entry_time and att.exit_time:
                    entry_dt = timezone.datetime.combine(att.date, att.entry_time)
                    exit_dt = timezone.datetime.combine(att.date, att.exit_time)
                    sec = (exit_dt - entry_dt).total_seconds()
                    if sec > 0:
                        total_seconds += sec
                elif att.entry_time and not att.exit_time and att.date == today:
                    entry_dt = timezone.datetime.combine(att.date, att.entry_time)
                    now_dt = timezone.datetime.combine(today, timezone.localtime().time())
                    sec = (now_dt - entry_dt).total_seconds()
                    if sec > 0:
                        total_seconds += sec

            if total_seconds > 0:
                hours, remainder = divmod(int(total_seconds), 3600)
                minutes, _ = divmod(remainder, 60)
                if hours > 0 and minutes > 0:
                    hr_str = "Hour" if hours == 1 else "Hours"
                    min_str = "Minute" if minutes == 1 else "Minutes"
                    att.total_day_duration_str = f"{hours} {hr_str} {minutes} {min_str}"
                elif hours > 0 and minutes == 0:
                    hr_str = "Hour" if hours == 1 else "Hours"
                    att.total_day_duration_str = f"{hours} {hr_str}"
                else:
                    if minutes == 0:
                        minutes = 1
                    min_str = "Minute" if minutes == 1 else "Minutes"
                    att.total_day_duration_str = f"{minutes} {min_str}"
            else:
                att.total_day_duration_str = "--"

            # Precompute Plan Expiry & Membership Status Badges per requirements
            if att.member and att.member.membership_end_date:
                days_rem = (att.member.membership_end_date - today).days
                att.plan_expiry_str = att.member.membership_end_date.strftime("%d %b %Y")
                if days_rem < 0 or not att.member.is_active:
                    att.status_text = "Expired Plan"
                    att.badge_class = "bg-danger text-white"
                    att.status_icon = "bi-x-circle-fill"
                elif days_rem <= 10:
                    day_word = "day" if days_rem == 1 else "days"
                    att.status_text = f"Expires in {days_rem} {day_word}"
                    att.badge_class = "bg-warning text-dark"
                    att.status_icon = "bi-exclamation-triangle-fill"
                else:
                    att.status_text = "Active Plan"
                    att.badge_class = "bg-success text-white"
                    att.status_icon = "bi-check-circle-fill"
            else:
                att.plan_expiry_str = "--"
                att.status_text = "Active Plan"
                att.badge_class = "bg-success text-white"
                att.status_icon = "bi-check-circle-fill"

        if status_filter == "all" and query_date == today:
            checked_member_ids = {att.member_id for att in raw_att_list if att.member_id}
            for m in Member.objects.filter(is_active=True):
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
                    hr_str = "Hour" if hours == 1 else "Hours"
                    min_str = "Minute" if minutes == 1 else "Minutes"
                    t_att.total_day_duration_str = f"{hours} {hr_str} {minutes} {min_str}"
                elif hours > 0 and minutes == 0:
                    hr_str = "Hour" if hours == 1 else "Hours"
                    t_att.total_day_duration_str = f"{hours} {hr_str}"
                else:
                    if minutes == 0:
                        minutes = 1
                    min_str = "Minute" if minutes == 1 else "Minutes"
                    t_att.total_day_duration_str = f"{minutes} {min_str}"
            else:
                t_att.total_day_duration_str = "--"

        if status_filter == "all" and query_date == today:
            for trn in Trainer.objects.filter(working_status=Trainer.STATUS_WORKING):
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
        alerts = []
        # 1. Long stay alerts (>3 hours / 180 mins)
        now_dt = timezone.localtime()
        for att in today_all_att.filter(status=Attendance.STATUS_INSIDE, entry_time__isnull=False):
            entry_dt = datetime.datetime.combine(today, att.entry_time)
            entry_dt = timezone.make_aware(entry_dt) if timezone.is_naive(entry_dt) else entry_dt
            mins_inside = int((now_dt - entry_dt).total_seconds() / 60)
            if mins_inside >= 180:
                h, m = divmod(mins_inside, 60)
                alerts.append({
                    "id": att.member.member_id,
                    "name": att.member.full_name,
                    "type": "long_stay",
                    "title": "Long Stay Alert",
                    "message": f"{att.member.full_name} has been inside the gym for {h}h {m}m.",
                    "time": f"{h}h {m}m",
                })

        # 2. Access Denied logs today
        for log in AttendanceLog.objects.filter(timestamp__date=today, entry_allowed=False)[:3]:
            name = log.member.full_name if log.member else f"FP: {log.fingerprint_id}"
            alerts.append({
                "id": log.member.member_id if log.member else "",
                "name": name,
                "type": "denied",
                "title": "Access Denied Alert",
                "message": f"Turnstile entry restricted for {name} ({log.reason}).",
                "time": log.timestamp.strftime("%I:%M %p"),
            })

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
        manual_form = ManualAttendanceForm(initial={"date": today.strftime("%Y-%m-%d")})

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
            "manual_form": manual_form,
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
            "gym_max_capacity": GYM_MAX_CAPACITY,
            # Alerts & Expired
            "alerts": alerts,
            "expired_members": expired_list,
            "expired_count": len(expired_list),
        }

    # ---------------------------------------------------------------
    # Sample Data Seeder (Ensures reference HTML members exist)
    # ---------------------------------------------------------------

    def _ensure_sample_data(self):
        today = timezone.localdate()
        # Create default membership plans
        plan_gold, _ = MembershipPlan.objects.get_or_create(
            name="Gold - 12 Months",
            defaults={"duration": 12, "duration_type": "months", "price": 15000, "access_type": "premium", "status": "active"}
        )
        plan_silver_6, _ = MembershipPlan.objects.get_or_create(
            name="Silver - 6 Months",
            defaults={"duration": 6, "duration_type": "months", "price": 8000, "access_type": "general", "status": "active"}
        )
        plan_plat_24, _ = MembershipPlan.objects.get_or_create(
            name="Platinum - 24 Months",
            defaults={"duration": 24, "duration_type": "months", "price": 28000, "access_type": "vip", "status": "active"}
        )
        plan_silver_3, _ = MembershipPlan.objects.get_or_create(
            name="Silver - 3 Months",
            defaults={"duration": 3, "duration_type": "months", "price": 4500, "access_type": "general", "status": "active"}
        )
        plan_gold_6, _ = MembershipPlan.objects.get_or_create(
            name="Gold - 6 Months",
            defaults={"duration": 6, "duration_type": "months", "price": 9500, "access_type": "premium", "status": "active"}
        )
        plan_plat_12, _ = MembershipPlan.objects.get_or_create(
            name="Platinum - 12 Months",
            defaults={"duration": 12, "duration_type": "months", "price": 18000, "access_type": "vip", "status": "active"}
        )
        plan_silver_12, _ = MembershipPlan.objects.get_or_create(
            name="Silver - 12 Months",
            defaults={"duration": 12, "duration_type": "months", "price": 12000, "access_type": "general", "status": "active"}
        )

        sample_members = [
            {
                "id": "ENT-1024", "name": "John Mathew", "gender": "M", "blood": "O+", "mobile": "+91 98765 43210",
                "join": "2024-02-15", "height": "178 cm", "weight": "82 kg", "goal": "Weight Loss", "med": "None",
                "plan": plan_gold, "active": True, "offset_min": 195, "inside": True, "fp": "FP-1024"
            },
            {
                "id": "ENT-1031", "name": "Priya Nair", "gender": "F", "blood": "A+", "mobile": "+91 90000 11122",
                "join": "2025-11-02", "height": "162 cm", "weight": "58 kg", "goal": "Muscle Toning", "med": "Mild Asthma",
                "plan": plan_silver_6, "active": True, "offset_min": 45, "inside": True, "fp": "FP-1031"
            },
            {
                "id": "ENT-1002", "name": "Arjun Menon", "gender": "M", "blood": "B+", "mobile": "+91 88888 22233",
                "join": "2023-06-20", "height": "172 cm", "weight": "76 kg", "goal": "Strength Building", "med": "Knee Sensitivity",
                "plan": plan_plat_24, "active": True, "offset_min": 205, "inside": True, "fp": "FP-1002"
            },
            {
                "id": "ENT-1077", "name": "Sneha Kurup", "gender": "F", "blood": "AB+", "mobile": "+91 99999 33344",
                "join": "2026-06-25", "height": "158 cm", "weight": "54 kg", "goal": "General Fitness", "med": "None",
                "plan": plan_silver_3, "active": True, "offset_min": 20, "inside": True, "fp": "FP-1077"
            },
            {
                "id": "ENT-0987", "name": "Vishnu Prasad", "gender": "M", "blood": "O-", "mobile": "+91 91234 56789",
                "join": "2022-01-10", "height": "180 cm", "weight": "90 kg", "goal": "Weight Loss", "med": "Hypertension",
                "plan": plan_gold, "active": False, "offset_min": 130, "inside": False, "fp": "FP-0987"
            },
            {
                "id": "ENT-1055", "name": "Meera Suresh", "gender": "F", "blood": "B-", "mobile": "+91 90909 12121",
                "join": "2025-01-18", "height": "165 cm", "weight": "60 kg", "goal": "Flexibility", "med": "None",
                "plan": plan_gold_6, "active": True, "offset_min": 15, "inside": True, "fp": "FP-1055"
            },
            {
                "id": "ENT-1090", "name": "Kiran Raj", "gender": "M", "blood": "A-", "mobile": "+91 93333 44455",
                "join": "2024-09-05", "height": "175 cm", "weight": "70 kg", "goal": "Muscle Gain", "med": "None",
                "plan": plan_plat_12, "active": True, "offset_min": 65, "inside": True, "fp": "FP-1090"
            },
            {
                "id": "ENT-0876", "name": "Divya Pillai", "gender": "F", "blood": "O+", "mobile": "+91 97777 88899",
                "join": "2021-03-30", "height": "160 cm", "weight": "62 kg", "goal": "Weight Maintenance", "med": "None",
                "plan": plan_silver_12, "active": True, "offset_min": 100, "inside": False, "fp": "FP-0876"
            },
        ]

        now_time = timezone.localtime().time()
        for m_data in sample_members:
            join_date = datetime.date.fromisoformat(m_data["join"])
            end_date = today + timedelta(days=180) if m_data["active"] else today - timedelta(days=15)
            member, _ = Member.objects.get_or_create(
                member_id=m_data["id"],
                defaults={
                    "full_name": m_data["name"],
                    "mobile_number": m_data["mobile"],
                    "gender": m_data["gender"],
                    "blood_group": m_data["blood"],
                    "height": m_data["height"],
                    "weight": m_data["weight"],
                    "fitness_goal": m_data["goal"],
                    "medical_condition": m_data["med"],
                    "membership_plan": m_data["plan"],
                    "join_date": join_date,
                    "membership_start_date": join_date,
                    "membership_end_date": end_date,
                    "is_active": m_data["active"],
                    "fingerprint_id": m_data["fp"],
                }
            )

            # Ensure attendance record exists for today
            if m_data["active"] or not m_data["inside"]:
                att = Attendance.objects.filter(member=member, date=today).first()
                if not att:
                    offset_dt = timezone.now() - timedelta(minutes=m_data["offset_min"])
                    entry_t = timezone.localtime(offset_dt).time()
                    exit_t = None if m_data["inside"] else now_time
                    status = Attendance.STATUS_INSIDE if m_data["inside"] else Attendance.STATUS_CHECKED_OUT

                    att = Attendance.objects.create(
                        member=member,
                        date=today,
                        entry_time=entry_t,
                        exit_time=exit_t,
                        status=status,
                        fingerprint_id=member.fingerprint_id,
                        entry_allowed=True,
                    )
                    AttendanceVisit.objects.create(
                        attendance=att,
                        visit_number=1,
                        entry_time=entry_t,
                        exit_time=exit_t
                    )

        # Backfill any Attendance records that don't have visits yet
        for att in Attendance.objects.filter(visits__isnull=True):
            if att.entry_time:
                AttendanceVisit.objects.create(
                    attendance=att,
                    visit_number=1,
                    entry_time=att.entry_time,
                    exit_time=att.exit_time
                )

        # Ensure John Mathew (ENT-1024) has >3 visits today to showcase scrollable entry/exit times
        john_att = Attendance.objects.filter(member__member_id="ENT-1024", date=today).first()
        if john_att and john_att.visits.count() <= 1:
            john_att.visits.all().delete()
            sample_visits = [
                (datetime.time(8, 10), datetime.time(9, 0)),
                (datetime.time(11, 30), datetime.time(12, 20)),
                (datetime.time(14, 15), datetime.time(15, 10)),
                (datetime.time(17, 40), None),
            ]
            for idx, (ent, ext) in enumerate(sample_visits, start=1):
                AttendanceVisit.objects.create(
                    attendance=john_att,
                    visit_number=idx,
                    entry_time=ent,
                    exit_time=ext
                )
            john_att.entry_time = datetime.time(8, 10)
            john_att.exit_time = None
            john_att.status = Attendance.STATUS_INSIDE
            john_att.save()

        # Ensure sample Trainers and TrainerAttendance exist for testing
        sample_trainers = [
            {"id": "TRN-101", "name": "Vikram Sharma", "desig": Trainer.DESIGNATION_HEAD, "mobile": "+91 98111 22233", "status": Trainer.STATUS_WORKING, "inside": True, "offset": 240},
            {"id": "TRN-102", "name": "Ananya Desai", "desig": Trainer.DESIGNATION_YOGA, "mobile": "+91 98222 33344", "status": Trainer.STATUS_WORKING, "inside": False, "offset": 300},
            {"id": "TRN-103", "name": "Rohit Verma", "desig": Trainer.DESIGNATION_FITNESS, "mobile": "+91 98333 44455", "status": Trainer.STATUS_WORKING, "inside": True, "offset": 120},
        ]
        for t_data in sample_trainers:
            trn, _ = Trainer.objects.get_or_create(
                trainer_id=t_data["id"],
                defaults={
                    "full_name": t_data["name"],
                    "designation": t_data["desig"],
                    "mobile_number": t_data["mobile"],
                    "working_status": t_data["status"],
                    "fingerprint_id": f"FP-{t_data['id']}",
                    "joining_date": today - timedelta(days=365)
                }
            )
            if not TrainerAttendance.objects.filter(trainer=trn, date=today).exists():
                offset_dt = timezone.now() - timedelta(minutes=t_data["offset"])
                entry_t = timezone.localtime(offset_dt).time()
                exit_t = None if t_data["inside"] else now_time
                status = TrainerAttendance.STATUS_INSIDE if t_data["inside"] else TrainerAttendance.STATUS_CHECKED_OUT

                t_att = TrainerAttendance.objects.create(
                    trainer=trn,
                    date=today,
                    entry_time=entry_t,
                    exit_time=exit_t,
                    status=status,
                    fingerprint_id=trn.fingerprint_id
                )
                TrainerAttendanceVisit.objects.create(
                    attendance=t_att,
                    visit_number=1,
                    entry_time=entry_t,
                    exit_time=exit_t
                )
