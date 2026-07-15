import datetime
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from main_app.models import Attendance, AttendanceVisit, Member, TrainerAttendance, TrainerAttendanceVisit
from masters.models import Trainer
from transactions.models import AttendanceLog
from .forms import AttendanceReportFilterForm


class AttendanceReportView(LoginRequiredMixin, View):
    """
    Reports module view.
    Provides attendance analytics with member/trainer tabs,
    filtering by preset/custom date range, member search, and plan.
    Handles AJAX requests for member/trainer detail popups and record deletion.
    """

    template_name = "reports/attendance_report.html"

    def get(self, request, *args, **kwargs):
        # Handle AJAX requests
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            action = request.GET.get("action")
            if action == "get_member_details":
                return self._ajax_member_details(request)
            elif action == "get_trainer_details":
                return self._ajax_trainer_details(request)
            elif action == "get_member_logs":
                return self._ajax_member_logs(request)

        context = self._build_context(request)
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "delete_attendance":
            return self._handle_delete_attendance(request)
        elif action == "delete_trainer_attendance":
            return self._handle_delete_trainer_attendance(request)
        messages.error(request, "Unknown action.")
        return redirect("attendance-report")

    # ---------------------------------------------------------------
    # Context Builder
    # ---------------------------------------------------------------

    def _build_context(self, request):
        form = AttendanceReportFilterForm(request.GET or None)
        today = timezone.localdate()
        start_date = today.replace(day=1)
        end_date = today
        date_preset = "this_month"
        member_search = ""
        plan_filter = None
        active_tab = request.GET.get("tab", "members")

        if form.is_valid():
            date_preset = form.cleaned_data.get("date_preset") or "this_month"
            member_search = form.cleaned_data.get("member_search") or ""
            plan_filter = form.cleaned_data.get("membership_plan")

            if date_preset == "today":
                start_date = today
                end_date = today
            elif date_preset == "yesterday":
                start_date = today - timedelta(days=1)
                end_date = today - timedelta(days=1)
            elif date_preset == "last_7_days":
                start_date = today - timedelta(days=6)
                end_date = today
            elif date_preset == "this_month":
                start_date = today.replace(day=1)
                end_date = today
            elif date_preset == "last_month":
                first_day_this_month = today.replace(day=1)
                last_day_last_month = first_day_this_month - timedelta(days=1)
                start_date = last_day_last_month.replace(day=1)
                end_date = last_day_last_month
            elif date_preset == "custom":
                s_val = form.cleaned_data.get("start_date")
                e_val = form.cleaned_data.get("end_date")
                if s_val and e_val:
                    start_date = s_val
                    end_date = e_val
                elif s_val:
                    start_date = s_val
                    end_date = s_val
                elif e_val:
                    start_date = e_val
                    end_date = e_val
        else:
            form = AttendanceReportFilterForm(initial={
                "date_preset": "this_month",
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
            })

        form.initial["start_date"] = start_date.strftime("%Y-%m-%d")
        form.initial["end_date"] = end_date.strftime("%Y-%m-%d")

        # ---- Dashboard Cards (Change 2) ----
        total_report_dates = Attendance.objects.filter(
            date__range=[start_date, end_date]
        ).values("date").distinct().count()

        active_memberships_count = Member.objects.filter(
            is_active=True, membership_end_date__gte=today
        ).count()

        expired_memberships_count = Member.objects.filter(
            membership_end_date__lt=today
        ).count()

        # ---- Build Records (Members or Trainers tab) ----
        date_groups = []
        records_count = 0

        if active_tab == "trainers":
            date_groups, records_count = self._build_trainer_groups(
                start_date, end_date, member_search
            )
        else:
            date_groups, records_count = self._build_member_groups(
                start_date, end_date, member_search, plan_filter
            )

        page_number = request.GET.get("page", 1)
        date_groups_page = Paginator(date_groups, 10).get_page(page_number)

        return {
            "filter_form": form,
            "start_date": start_date,
            "end_date": end_date,
            "date_preset": date_preset,
            "total_report_dates": total_report_dates,
            "active_memberships_count": active_memberships_count,
            "expired_memberships_count": expired_memberships_count,
            "date_groups": date_groups_page,
            "records_count": records_count,
            "active_tab": active_tab,
            "has_filters": bool(member_search or plan_filter or date_preset != "this_month"),
        }

    def _build_member_groups(self, start_date, end_date, member_search, plan_filter):
        qs = Attendance.objects.select_related(
            "member", "member__membership_plan"
        ).prefetch_related("visits").filter(date__range=[start_date, end_date])

        if member_search:
            qs = qs.filter(
                Q(member__member_id__icontains=member_search) |
                Q(member__full_name__icontains=member_search) |
                Q(member__mobile_number__icontains=member_search) |
                Q(fingerprint_id__icontains=member_search)
            )

        if plan_filter:
            qs = qs.filter(member__membership_plan=plan_filter)

        raw_list = list(qs.order_by("-date", "-entry_time", "-id"))
        grouped = {}
        for att in raw_list:
            key = (att.member_id, att.date)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(att)

        dedup_list = []
        for key, group in grouped.items():
            primary_att = group[0]
            all_visits = []
            for att in group:
                vs = list(att.visits.all())
                if not vs and att.entry_time:
                    vs = [AttendanceVisit(attendance=att, visit_number=1, entry_time=att.entry_time, exit_time=att.exit_time)]
                all_visits.extend(vs)

            all_visits.sort(key=lambda v: (v.entry_time or datetime.time.min, v.visit_number))
            for idx, v in enumerate(all_visits, start=1):
                if v.visit_number != idx:
                    v.visit_number = idx

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

            total_seconds = 0
            if all_visits:
                primary_att.entry_time = all_visits[0].entry_time or primary_att.entry_time
                primary_att.exit_time = all_visits[-1].exit_time if all(v.exit_time is not None for v in all_visits) else None
                for v in all_visits:
                    if v.entry_time and v.exit_time:
                        entry_dt = datetime.datetime.combine(primary_att.date, v.entry_time)
                        exit_dt = datetime.datetime.combine(primary_att.date, v.exit_time)
                        if exit_dt < entry_dt:
                            exit_dt += timedelta(days=1)
                        sec = (exit_dt - entry_dt).total_seconds()
                        if sec > 0:
                            total_seconds += sec
            elif primary_att.entry_time and primary_att.exit_time:
                entry_dt = datetime.datetime.combine(primary_att.date, primary_att.entry_time)
                exit_dt = datetime.datetime.combine(primary_att.date, primary_att.exit_time)
                if exit_dt < entry_dt:
                    exit_dt += timedelta(days=1)
                sec = (exit_dt - entry_dt).total_seconds()
                if sec > 0:
                    total_seconds += sec

            if total_seconds > 0:
                hours, remainder = divmod(int(total_seconds), 3600)
                minutes, _ = divmod(remainder, 60)
                if hours > 0 and minutes > 0:
                    dur_str = f"{hours}h {minutes}m"
                elif hours > 0:
                    dur_str = f"{hours}h 00m"
                else:
                    dur_str = f"{max(1, minutes)}m"

                limit_mins = 24 * 60
                if primary_att.member and primary_att.member.membership_plan and primary_att.member.membership_plan.daily_access_hours and not primary_att.member.membership_plan.is_full_day_access:
                    limit_mins = primary_att.member.membership_plan.daily_access_hours * 60

                total_mins = int(total_seconds / 60)
                remaining_mins = limit_mins - total_mins

                if remaining_mins <= 0:
                    primary_att.duration_badge_class = "badge bg-danger-subtle text-danger border border-danger-subtle px-2 py-1 fw-semibold"
                    primary_att.total_day_duration_str = f"🔴 {dur_str}"
                elif remaining_mins <= 30:
                    primary_att.duration_badge_class = "badge bg-warning-subtle text-warning-emphasis border border-warning-subtle px-2 py-1 fw-semibold"
                    primary_att.total_day_duration_str = f"🟠 {dur_str}"
                else:
                    primary_att.duration_badge_class = "badge bg-success-subtle text-success border border-success-subtle px-2 py-1 fw-semibold"
                    primary_att.total_day_duration_str = f"🟢 {dur_str}"
            else:
                primary_att.total_day_duration_str = "--"
                primary_att.duration_badge_class = "badge bg-light text-dark border px-2 py-1 fw-semibold"

            dedup_list.append(primary_att)

        records_count = len(dedup_list)
        records_by_date = {}
        for att in dedup_list:
            if att.date not in records_by_date:
                records_by_date[att.date] = []
            records_by_date[att.date].append(att)

        date_groups = []
        for d_key, recs in records_by_date.items():
            d_mins = 0
            d_count = 0
            for r in recs:
                if r.visit_list:
                    for v in r.visit_list:
                        if v.entry_time and v.exit_time:
                            edt = datetime.datetime.combine(r.date, v.entry_time)
                            xdt = datetime.datetime.combine(r.date, v.exit_time)
                            if xdt < edt:
                                xdt += timedelta(days=1)
                            d_mins += (xdt - edt).total_seconds() / 60.0
                            d_count += 1
                elif r.entry_time and r.exit_time:
                    edt = datetime.datetime.combine(r.date, r.entry_time)
                    xdt = datetime.datetime.combine(r.date, r.exit_time)
                    if xdt < edt:
                        xdt += timedelta(days=1)
                    d_mins += (xdt - edt).total_seconds() / 60.0
                    d_count += 1
            d_avg = f"{int(d_mins // d_count // 60)}h {int((d_mins // d_count) % 60)}m" if d_count > 0 else "--"

            date_groups.append({
                "date": d_key,
                "date_formatted": d_key.strftime("%A, %d %B %Y"),
                "records": recs,
                "total_checkins": len(recs),
                "avg_duration": d_avg,
            })

        return date_groups, records_count

    def _build_trainer_groups(self, start_date, end_date, search):
        qs = TrainerAttendance.objects.select_related(
            "trainer"
        ).prefetch_related("visits").filter(date__range=[start_date, end_date])

        if search:
            qs = qs.filter(
                Q(trainer__trainer_id__icontains=search) |
                Q(trainer__full_name__icontains=search) |
                Q(trainer__mobile_number__icontains=search)
            )

        raw_list = list(qs.order_by("-date", "-entry_time", "-id"))
        grouped = {}
        for att in raw_list:
            key = (att.trainer_id, att.date)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(att)

        dedup_list = []
        for key, group in grouped.items():
            primary_att = group[0]
            all_visits = []
            for att in group:
                vs = list(att.visits.all())
                if not vs and att.entry_time:
                    vs = [TrainerAttendanceVisit(attendance=att, visit_number=1, entry_time=att.entry_time, exit_time=att.exit_time)]
                all_visits.extend(vs)

            all_visits.sort(key=lambda v: (v.entry_time or datetime.time.min, v.visit_number))
            for idx, v in enumerate(all_visits, start=1):
                if v.visit_number != idx:
                    v.visit_number = idx

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

            total_seconds = 0
            if all_visits:
                primary_att.entry_time = all_visits[0].entry_time or primary_att.entry_time
                primary_att.exit_time = all_visits[-1].exit_time if all(v.exit_time is not None for v in all_visits) else None
                for v in all_visits:
                    if v.entry_time and v.exit_time:
                        entry_dt = datetime.datetime.combine(primary_att.date, v.entry_time)
                        exit_dt = datetime.datetime.combine(primary_att.date, v.exit_time)
                        if exit_dt < entry_dt:
                            exit_dt += timedelta(days=1)
                        sec = (exit_dt - entry_dt).total_seconds()
                        if sec > 0:
                            total_seconds += sec
            elif primary_att.entry_time and primary_att.exit_time:
                entry_dt = datetime.datetime.combine(primary_att.date, primary_att.entry_time)
                exit_dt = datetime.datetime.combine(primary_att.date, primary_att.exit_time)
                if exit_dt < entry_dt:
                    exit_dt += timedelta(days=1)
                sec = (exit_dt - entry_dt).total_seconds()
                if sec > 0:
                    total_seconds += sec

            if total_seconds > 0:
                hours, remainder = divmod(int(total_seconds), 3600)
                minutes, _ = divmod(remainder, 60)
                if hours > 0 and minutes > 0:
                    dur_str = f"{hours}h {minutes}m"
                elif hours > 0:
                    dur_str = f"{hours}h 00m"
                else:
                    dur_str = f"{max(1, minutes)}m"
            else:
                dur_str = "--"

            primary_att.total_day_duration_str = dur_str
            dedup_list.append(primary_att)

        records_count = len(dedup_list)
        records_by_date = {}
        for att in dedup_list:
            if att.date not in records_by_date:
                records_by_date[att.date] = []
            records_by_date[att.date].append(att)

        date_groups = []
        for d_key, recs in records_by_date.items():
            d_mins = 0
            d_count = 0
            for r in recs:
                if r.visit_list:
                    for v in r.visit_list:
                        if v.entry_time and v.exit_time:
                            edt = datetime.datetime.combine(r.date, v.entry_time)
                            xdt = datetime.datetime.combine(r.date, v.exit_time)
                            if xdt < edt:
                                xdt += timedelta(days=1)
                            d_mins += (xdt - edt).total_seconds() / 60.0
                            d_count += 1
                elif r.entry_time and r.exit_time:
                    edt = datetime.datetime.combine(r.date, r.entry_time)
                    xdt = datetime.datetime.combine(r.date, r.exit_time)
                    if xdt < edt:
                        xdt += timedelta(days=1)
                    d_mins += (xdt - edt).total_seconds() / 60.0
                    d_count += 1
            d_avg = f"{int(d_mins // d_count // 60)}h {int((d_mins // d_count) % 60)}m" if d_count > 0 else "--"

            date_groups.append({
                "date": d_key,
                "date_formatted": d_key.strftime("%A, %d %B %Y"),
                "records": recs,
                "total_checkins": len(recs),
                "avg_duration": d_avg,
            })

        return date_groups, records_count

    # ---------------------------------------------------------------
    # AJAX Handlers
    # ---------------------------------------------------------------

    def _ajax_member_details(self, request):
        """Return member profile + attendance summary (same as attendance management popup)."""
        member_id = request.GET.get("member_id", "").strip()
        member = get_object_or_404(Member, member_id=member_id)

        # Calculate BMI
        bmi_str = "--"
        try:
            h_m = float(member.height.replace("cm", "").strip()) / 100.0
            w_kg = float(member.weight.replace("kg", "").strip())
            if h_m > 0:
                bmi_str = f"{w_kg / (h_m * h_m):.1f}"
        except (ValueError, ZeroDivisionError, AttributeError):
            bmi_str = "--"

        # Joined since
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

        # Attendance summary
        today = timezone.localdate()
        today_att = Attendance.objects.filter(member=member, date=today).first()
        checkin_today = today_att.entry_time.strftime("%H:%M") if (today_att and today_att.entry_time) else "--"
        duration_inside = today_att.duration if today_att else "--"
        if today_att and today_att.status == Attendance.STATUS_INSIDE and today_att.entry_time:
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

        plan_amount = float(member.membership_plan.final_price if member.membership_plan and hasattr(member.membership_plan, 'final_price') and member.membership_plan.final_price else (member.membership_plan.price if member.membership_plan else 0.0))
        amount_paid = float(member.amount_paid or 0.0)
        remaining_amount = max(0.0, plan_amount - amount_paid)

        photo_url = member.photo.url if member.photo else f"https://ui-avatars.com/api/?name={member.full_name}&background=random&size=128"

        return JsonResponse({
            "id": member.member_id,
            "name": member.full_name,
            "photo_url": photo_url,
            "status": "Active" if not member.is_expired else "Expired",
            "gender": member.get_gender_display() or "--",
            "blood_group": member.blood_group or "--",
            "mobile": member.mobile_number,
            "join_date": member.join_date.strftime("%Y-%m-%d"),
            "expiry_date": member.membership_end_date.strftime("%d-%b-%Y") if member.membership_end_date else "--",
            "height": member.height or "--",
            "weight": member.weight or "--",
            "bmi": bmi_str,
            "fitness_goal": member.fitness_goal or "--",
            "medical_condition": member.medical_condition or "None",
            "plan": member.membership_plan.name if member.membership_plan else "General Plan",
            "plan_amount": f"{plan_amount:.2f}",
            "amount_paid": f"{amount_paid:.2f}",
            "remaining_amount": f"{remaining_amount:.2f}",
            "joined_since": joined_since,
            "total_visits": total_visits,
            "last_visit": last_visit,
            "checkin_today": checkin_today,
            "duration_inside": duration_inside or "--",
            "month_visits": f"{month_visits} visits",
            "total_attendance": f"{total_visits} visits",
        })

    def _ajax_trainer_details(self, request):
        """Return trainer profile details."""
        trainer_id = request.GET.get("trainer_id", "").strip()
        trainer = get_object_or_404(Trainer, trainer_id=trainer_id)

        today = timezone.localdate()
        month_start = today.replace(day=1)
        total_visits = TrainerAttendance.objects.filter(trainer=trainer).count()
        month_visits = TrainerAttendance.objects.filter(trainer=trainer, date__gte=month_start).count()
        last_visit_obj = TrainerAttendance.objects.filter(trainer=trainer).order_by("-date", "-entry_time").first()
        last_visit = last_visit_obj.date.strftime("%Y-%m-%d") if last_visit_obj else trainer.joining_date.strftime("%Y-%m-%d")

        today_att = TrainerAttendance.objects.filter(trainer=trainer, date=today).first()
        checkin_today = today_att.entry_time.strftime("%H:%M") if (today_att and today_att.entry_time) else "--"
        duration_inside = today_att.duration if today_att else "--"

        photo_url = trainer.photo.url if trainer.photo else f"https://ui-avatars.com/api/?name={trainer.full_name}&background=random&size=128"

        return JsonResponse({
            "id": trainer.trainer_id,
            "name": trainer.full_name,
            "photo_url": photo_url,
            "status": trainer.working_status,
            "gender": trainer.get_gender_display() or "--",
            "blood_group": "--",
            "mobile": trainer.mobile_number,
            "join_date": trainer.joining_date.strftime("%Y-%m-%d"),
            "expiry_date": "--",
            "height": "--",
            "weight": "--",
            "bmi": "--",
            "fitness_goal": trainer.get_designation_display() if hasattr(trainer, 'get_designation_display') else trainer.designation,
            "medical_condition": "None",
            "plan": trainer.get_designation_display() if hasattr(trainer, 'get_designation_display') else trainer.designation,
            "joined_since": f"{max(1, (today - trainer.joining_date).days)} Days",
            "total_visits": total_visits,
            "last_visit": last_visit,
            "checkin_today": checkin_today,
            "duration_inside": duration_inside or "--",
            "month_visits": f"{month_visits} visits",
            "total_attendance": f"{total_visits} visits",
        })

    def _ajax_member_logs(self, request):
        """Return access audit trail logs for a member (existing functionality)."""
        member_id = request.GET.get("member_id", "").strip()
        if not member_id:
            return JsonResponse({"error": "Member ID is required."}, status=400)

        member = Member.objects.filter(member_id=member_id).first()
        if not member:
            return JsonResponse({"error": "Member not found."}, status=404)

        logs = AttendanceLog.objects.filter(member=member).order_by("-timestamp")[:20]
        log_list = []
        for l in logs:
            log_list.append({
                "id": l.pk,
                "event_type": l.get_event_type_display(),
                "timestamp": l.timestamp.strftime("%d %b %Y, %H:%M"),
                "entry_allowed": l.entry_allowed,
                "reason": l.reason or ("Access Granted" if l.entry_allowed else "Access Denied"),
                "fingerprint_id": l.fingerprint_id or member.fingerprint_id or "--",
            })

        history_qs = Attendance.objects.filter(member=member)
        total_visits = history_qs.count()

        return JsonResponse({
            "member_name": member.full_name,
            "member_id": member.member_id,
            "plan_name": member.membership_plan.name if member.membership_plan else "General Plan",
            "photo_url": member.photo.url if member.photo else f"https://ui-avatars.com/api/?name={member.full_name}&background=random&size=84",
            "total_visits": total_visits,
            "logs": log_list,
        })

    # ---------------------------------------------------------------
    # POST Handlers
    # ---------------------------------------------------------------

    def _handle_delete_attendance(self, request):
        """Delete a member attendance record."""
        att_id = request.POST.get("attendance_id")
        try:
            att = Attendance.objects.get(pk=att_id)
            member_name = att.member.full_name
            att_date = att.date.strftime("%d %b %Y")
            att.delete()
            messages.success(request, f"Attendance record for {member_name} on {att_date} deleted successfully.")
        except Attendance.DoesNotExist:
            messages.error(request, "Attendance record not found.")
        return redirect("attendance-report")

    def _handle_delete_trainer_attendance(self, request):
        """Delete a trainer attendance record."""
        att_id = request.POST.get("attendance_id")
        try:
            att = TrainerAttendance.objects.get(pk=att_id)
            trainer_name = att.trainer.full_name
            att_date = att.date.strftime("%d %b %Y")
            att.delete()
            messages.success(request, f"Trainer attendance record for {trainer_name} on {att_date} deleted successfully.")
        except TrainerAttendance.DoesNotExist:
            messages.error(request, "Trainer attendance record not found.")
        return redirect("attendance-report")
