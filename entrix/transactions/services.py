"""
Attendance domain services
==========================

Canonical, transport-agnostic business logic for recording gym attendance.

These functions are the single source of truth for turning a raw "punch"
(from a biometric device, an API, or a manual admin action) into the correct
``Attendance`` / ``TrainerAttendance`` state, including the per-day visit
normalisation and access-control rules.

Keeping this logic here (instead of inside a view) means the biometric
integration layer, the manual check-in flow, and any future API can all share
exactly the same rules — check-in/out toggling, expired/inactive rejection,
multi-visit handling — with no duplication or drift.
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from main_app.models import (
    Attendance,
    AttendanceVisit,
    Member,
    TrainerAttendance,
    TrainerAttendanceVisit,
)
from masters.models import Trainer
from .models import AttendanceLog


# ---------------------------------------------------------------------------
# Result value object
# ---------------------------------------------------------------------------

@dataclass
class PunchResult:
    """Outcome of a single punch, returned to whichever layer invoked it."""

    ok: bool
    event: str          # "check_in", "check_out", "denied", "noop"
    message: str
    subject_type: Optional[str] = None   # "member" | "trainer"
    subject_id: Optional[str] = None     # member_id / trainer_id
    subject_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------

def resolve_biometric_identity(pin):
    """
    Map a raw device PIN / biometric ID to a Member or Trainer.

    Devices are enrolled against the system-generated ``biometric_id``. We also
    fall back to a Member's legacy ``fingerprint_id`` so older enrolments keep
    working. Returns a tuple ``(kind, obj)`` where kind is "member",
    "trainer", or ``None`` when the PIN is unrecognised.
    """
    pin = (str(pin) if pin is not None else "").strip()
    if not pin:
        return None, None

    member = Member.objects.filter(biometric_id=pin).first()
    if member:
        return "member", member

    trainer = Trainer.objects.filter(biometric_id=pin).first()
    if trainer:
        return "trainer", trainer

    member = Member.objects.filter(fingerprint_id=pin).first()
    if member:
        return "member", member

    return None, None


# ---------------------------------------------------------------------------
# Member attendance
# ---------------------------------------------------------------------------

@transaction.atomic
def record_member_punch(member, *, punch_time=None, punch_date=None,
                        fingerprint_id=None, force_direction=None):
    """
    Record a member entry/exit, automatically toggling between check-in and
    check-out based on the member's current state for the day.

    Access is only granted to active members with a valid (non-expired)
    membership; every attempt — granted or denied — is written to the
    immutable ``AttendanceLog`` audit trail.

    ``force_direction`` may be "check_in" or "check_out" to override the
    automatic toggle (used when the device reports an explicit punch state).
    """
    today = punch_date or timezone.localdate()
    now_time = punch_time or timezone.localtime().time()
    fp = fingerprint_id or member.fingerprint_id or getattr(member, "biometric_id", None)

    # --- Access control: inactive or expired members are denied entry ---
    if member.is_expired or not member.is_active:
        reason = ("Membership expired. Access restricted."
                  if member.is_expired else "Membership inactive. Access restricted.")
        AttendanceLog.objects.create(
            member=member,
            fingerprint_id=fp or "UNKNOWN",
            event_type=AttendanceLog.EVENT_DENIED_EXPIRED,
            entry_allowed=False,
            reason=reason,
        )
        return PunchResult(
            ok=False, event="denied", message=reason,
            subject_type="member", subject_id=member.member_id, subject_name=member.full_name,
        )

    att = Attendance.objects.filter(member=member, date=today).first()
    currently_inside = bool(
        att and (att.status == Attendance.STATUS_INSIDE
                 or (att.visits.filter(exit_time__isnull=True).exists()))
    )

    # Decide direction.
    if force_direction == "check_in":
        do_checkout = False
    elif force_direction == "check_out":
        do_checkout = True
    else:
        do_checkout = currently_inside

    if do_checkout and att and currently_inside:
        return _member_check_out(att, now_time, fp)
    if not do_checkout:
        if att and currently_inside:
            return PunchResult(
                ok=True, event="noop",
                message=f"{member.full_name} is already inside the gym.",
                subject_type="member", subject_id=member.member_id, subject_name=member.full_name,
            )
        return _member_check_in(member, att, today, now_time, fp)

    # force_checkout requested but member isn't inside — nothing to do.
    return PunchResult(
        ok=True, event="noop",
        message=f"{member.full_name} is not currently inside.",
        subject_type="member", subject_id=member.member_id, subject_name=member.full_name,
    )


def _member_check_in(member, att, today, now_time, fp):
    if att:
        next_visit_num = att.visits.count() + 1
        AttendanceVisit.objects.create(
            attendance=att, visit_number=next_visit_num, entry_time=now_time
        )
        att.status = Attendance.STATUS_INSIDE
        att.save()
    else:
        att = Attendance.objects.create(
            member=member, date=today, entry_time=now_time,
            status=Attendance.STATUS_INSIDE, fingerprint_id=fp,
            entry_allowed=True, membership_status_at_entry="Active",
        )
        AttendanceVisit.objects.create(attendance=att, visit_number=1, entry_time=now_time)

    AttendanceLog.objects.create(
        member=member, fingerprint_id=fp or f"FP-{member.member_id}",
        event_type=AttendanceLog.EVENT_CHECKIN, entry_allowed=True,
        reason="Successful check-in.",
    )
    return PunchResult(
        ok=True, event="check_in",
        message=f"Check-in recorded for {member.full_name}.",
        subject_type="member", subject_id=member.member_id, subject_name=member.full_name,
    )


def _member_check_out(att, now_time, fp):
    last_visit = att.visits.filter(exit_time__isnull=True).order_by("-visit_number").first()
    if not last_visit:
        last_visit = att.visits.order_by("-visit_number").first()
    if last_visit:
        last_visit.exit_time = now_time
        last_visit.save()
    elif att.entry_time:
        AttendanceVisit.objects.create(
            attendance=att, visit_number=1, entry_time=att.entry_time, exit_time=now_time
        )
    att.status = Attendance.STATUS_CHECKED_OUT
    att.exit_time = now_time
    att.save()

    AttendanceLog.objects.create(
        member=att.member, fingerprint_id=fp or f"FP-{att.member.member_id}",
        event_type=AttendanceLog.EVENT_CHECKOUT, entry_allowed=True,
        reason="Check-out recorded.",
    )
    return PunchResult(
        ok=True, event="check_out",
        message=f"Check-out recorded for {att.member.full_name}.",
        subject_type="member", subject_id=att.member.member_id, subject_name=att.member.full_name,
    )


# ---------------------------------------------------------------------------
# Trainer attendance
# ---------------------------------------------------------------------------

@transaction.atomic
def record_trainer_punch(trainer, *, punch_time=None, punch_date=None,
                         fingerprint_id=None, force_direction=None):
    """
    Record a trainer entry/exit, toggling between check-in and check-out based
    on the trainer's current state for the day. Trainers are marked purely on
    biometric presence (no membership rules apply).
    """
    today = punch_date or timezone.localdate()
    now_time = punch_time or timezone.localtime().time()
    fp = fingerprint_id or getattr(trainer, "biometric_id", None)

    att = TrainerAttendance.objects.filter(trainer=trainer, date=today).first()
    currently_inside = bool(
        att and (att.status == TrainerAttendance.STATUS_INSIDE
                 or att.visits.filter(exit_time__isnull=True).exists())
    )

    if force_direction == "check_in":
        do_checkout = False
    elif force_direction == "check_out":
        do_checkout = True
    else:
        do_checkout = currently_inside

    if do_checkout and att and currently_inside:
        last_visit = att.visits.filter(exit_time__isnull=True).order_by("-visit_number").first()
        if not last_visit:
            last_visit = att.visits.order_by("-visit_number").first()
        if last_visit:
            last_visit.exit_time = now_time
            last_visit.save()
        elif att.entry_time:
            TrainerAttendanceVisit.objects.create(
                attendance=att, visit_number=1, entry_time=att.entry_time, exit_time=now_time
            )
        att.status = TrainerAttendance.STATUS_CHECKED_OUT
        att.exit_time = now_time
        att.save()
        return PunchResult(
            ok=True, event="check_out",
            message=f"Check-out recorded for Trainer {trainer.full_name}.",
            subject_type="trainer", subject_id=trainer.trainer_id, subject_name=trainer.full_name,
        )

    if not do_checkout:
        if att and currently_inside:
            return PunchResult(
                ok=True, event="noop",
                message=f"Trainer {trainer.full_name} is already inside.",
                subject_type="trainer", subject_id=trainer.trainer_id, subject_name=trainer.full_name,
            )
        if att:
            next_visit_num = att.visits.count() + 1
            TrainerAttendanceVisit.objects.create(
                attendance=att, visit_number=next_visit_num, entry_time=now_time
            )
            att.status = TrainerAttendance.STATUS_INSIDE
            att.save()
        else:
            att = TrainerAttendance.objects.create(
                trainer=trainer, date=today, entry_time=now_time,
                status=TrainerAttendance.STATUS_INSIDE, fingerprint_id=fp,
            )
            TrainerAttendanceVisit.objects.create(attendance=att, visit_number=1, entry_time=now_time)
        return PunchResult(
            ok=True, event="check_in",
            message=f"Check-in recorded for Trainer {trainer.full_name}.",
            subject_type="trainer", subject_id=trainer.trainer_id, subject_name=trainer.full_name,
        )

    return PunchResult(
        ok=True, event="noop",
        message=f"Trainer {trainer.full_name} is not currently inside.",
        subject_type="trainer", subject_id=trainer.trainer_id, subject_name=trainer.full_name,
    )


# ---------------------------------------------------------------------------
# Unified punch entry point (used by the biometric integration layer)
# ---------------------------------------------------------------------------

def record_biometric_punch(pin, *, punch_time=None, punch_date=None, force_direction=None):
    """
    Resolve a device PIN to a member or trainer and record the punch.

    This is the one call the ADMS layer makes per attendance record; all the
    access rules and check-in/out toggling live in the functions above.
    """
    kind, obj = resolve_biometric_identity(pin)
    if kind == "member":
        return record_member_punch(
            obj, punch_time=punch_time, punch_date=punch_date,
            fingerprint_id=pin, force_direction=force_direction,
        )
    if kind == "trainer":
        return record_trainer_punch(
            obj, punch_time=punch_time, punch_date=punch_date,
            fingerprint_id=pin, force_direction=force_direction,
        )

    # Unknown fingerprint — log the denied/unrecognised attempt for auditing.
    AttendanceLog.objects.create(
        member=None,
        fingerprint_id=str(pin)[:50],
        event_type=AttendanceLog.EVENT_DENIED_UNKNOWN,
        entry_allowed=False,
        reason="Unrecognized biometric ID at device.",
    )
    return PunchResult(
        ok=False, event="denied",
        message=f"Unrecognized biometric ID: {pin}",
    )


# ---------------------------------------------------------------------------
# Attendance DISPLAY annotations (read-only, single source of truth for UI)
# ---------------------------------------------------------------------------
#
# The Attendance Management page and the Dashboard "Recent Attendance" widget
# must render member attendance identically — same Entry/Exit pairs, same
# duration string, same colour-coded badges and status. To guarantee they can
# never drift, the exact display rules live here and BOTH views call them.
#
# These helpers only annotate in-memory Python attributes on the passed
# ``Attendance`` instances; they NEVER write to the database (the AM view keeps
# its own DB-healing/dedup pass separately).

def annotate_attendance_duration(att, today):
    """Attach ``total_day_minutes``, ``total_day_duration_str`` and
    ``duration_badge_class`` to a member ``Attendance`` record, aggregating
    across all visits for the day. Requires ``att.visit_list`` to be set
    (a possibly-empty list of visits). Falls back to the record's own
    entry/exit times when no visits are present."""
    visits = getattr(att, "visit_list", None) or []
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
            dur_str = f"{hours}h {minutes}m"
        elif hours > 0:
            dur_str = f"{hours}h 00m"
        else:
            dur_str = f"{max(1, minutes)}m"

        limit_mins = 24 * 60
        plan = att.member.membership_plan if att.member else None
        if plan and plan.daily_access_hours and not plan.is_full_day_access:
            limit_mins = plan.daily_access_hours * 60

        total_mins = int(total_seconds / 60)
        att.total_day_minutes = total_mins
        remaining_mins = limit_mins - total_mins

        if remaining_mins <= 0:
            att.duration_badge_class = "badge bg-danger-subtle text-danger border border-danger-subtle px-2 py-1 fw-semibold"
            att.total_day_duration_str = f"\U0001F534 {dur_str}"
        elif remaining_mins <= 30:
            att.duration_badge_class = "badge bg-warning-subtle text-warning-emphasis border border-warning-subtle px-2 py-1 fw-semibold"
            att.total_day_duration_str = f"\U0001F7E0 {dur_str}"
        else:
            att.duration_badge_class = "badge bg-success-subtle text-success border border-success-subtle px-2 py-1 fw-semibold"
            att.total_day_duration_str = f"\U0001F7E2 {dur_str}"
    else:
        att.total_day_minutes = 0
        att.total_day_duration_str = "--"
        att.duration_badge_class = "badge bg-light text-dark border px-2 py-1 fw-semibold"

    return att


def annotate_member_plan_status(att, today):
    """Attach ``plan_expiry_str``, ``status_text``, ``badge_class`` and
    ``status_icon`` describing the member's membership state, identical to the
    Attendance Management page."""
    member = att.member
    if member and member.membership_end_date:
        days_rem = (member.membership_end_date - today).days
        att.plan_expiry_str = member.membership_end_date.strftime("%d %b %Y")
        if days_rem < 0 or not member.is_active:
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

    return att


def build_recent_member_attendance(limit=8, today=None):
    """Return the most recent member ``Attendance`` records (newest first),
    deduplicated per (member, date) with ``visit_list`` built and the same
    duration/status annotations the Attendance Management page uses.

    This is what the Dashboard "Recent Attendance" widget renders, making the
    Attendance Records the single source of truth. Read-only: no DB writes, so
    the dashboard never mutates attendance state.
    """
    today = today or timezone.localdate()

    # Fetch more than `limit` rows because several rows may collapse into one
    # (member, date) group after dedup.
    raw = list(
        Attendance.objects.select_related("member", "member__membership_plan")
        .prefetch_related("visits")
        .order_by("-date", "-entry_time", "-id")[: max(limit * 4, limit)]
    )

    grouped = {}
    order = []
    for att in raw:
        key = (att.member_id, att.date)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(att)

    result = []
    for key in order:
        group = grouped[key]
        primary = group[0]

        all_visits = []
        for att in group:
            vs = list(att.visits.all())
            if not vs and att.entry_time:
                vs = [AttendanceVisit(
                    attendance=att, visit_number=1,
                    entry_time=att.entry_time, exit_time=att.exit_time,
                )]
            all_visits.extend(vs)

        all_visits.sort(key=lambda v: (v.entry_time or datetime.time.min, v.visit_number))
        for idx, v in enumerate(all_visits, start=1):
            v.visit_number = idx

        primary.visit_list = all_visits
        primary.visits_count = len(all_visits)
        if len(all_visits) <= 1:
            primary.visit_label = ""
        elif len(all_visits) == 2:
            primary.visit_label = "2nd Time"
        elif len(all_visits) == 3:
            primary.visit_label = "3rd Time"
        else:
            primary.visit_label = f"{len(all_visits)}th Time"

        if all_visits:
            primary.entry_time = all_visits[0].entry_time or primary.entry_time
            primary.exit_time = (
                all_visits[-1].exit_time
                if all(v.exit_time is not None for v in all_visits) else None
            )
            # Derive status in-memory only (no save — read-only widget).
            primary.status = (
                Attendance.STATUS_INSIDE
                if any(v.exit_time is None for v in all_visits)
                else Attendance.STATUS_CHECKED_OUT
            )

        annotate_attendance_duration(primary, today)
        annotate_member_plan_status(primary, today)
        result.append(primary)

        if len(result) >= limit:
            break

    return result


def build_member_detail_payload(member):
    """Build the member profile + attendance-summary dict shown by the shared
    "Member Profile & Attendance Details" popup (#memberModal).

    This is the single source of truth for that popup's data so the Attendance
    Management page, the Dashboard Membership Expiry list and any other caller
    render identical fields. Returns a plain dict ready for ``JsonResponse``.
    """
    # Calculate BMI from the stored height/weight text fields.
    bmi_str = "--"
    try:
        h_m = float(member.height.replace("cm", "").strip()) / 100.0
        w_kg = float(member.weight.replace("kg", "").strip())
        if h_m > 0:
            bmi_str = f"{w_kg / (h_m * h_m):.1f}"
    except (ValueError, ZeroDivisionError, AttributeError):
        bmi_str = str(member.bmi) if member.bmi is not None else "--"

    # Joined-since, expressed in years / months / days.
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

    # Attendance summary stats.
    today = timezone.localdate()
    today_att = Attendance.objects.filter(member=member, date=today).first()
    checkin_today = today_att.entry_time.strftime("%H:%M") if (today_att and today_att.entry_time) else "--"
    duration_inside = today_att.duration if today_att else "Left"
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

    plan = member.membership_plan
    plan_amount = float(
        plan.final_price if plan and getattr(plan, "final_price", None) else (plan.price if plan else 0.0)
    )
    amount_paid = float(member.amount_paid or 0.0)
    remaining_amount = max(0.0, plan_amount - amount_paid)

    photo_url = member.photo.url if member.photo else f"https://ui-avatars.com/api/?name={member.full_name}&background=random&size=128"

    return {
        "id": member.member_id,
        "name": member.full_name,
        "photo_url": photo_url,
        "status": "Active" if not member.is_expired else "Expired",
        "gender": member.get_gender_display() or "Male",
        "blood_group": member.blood_group or "O+",
        "mobile": member.mobile_number,
        "email": member.email or "--",
        "username": getattr(member, "username", "") or "--",
        "address": member.address or "--",
        "dob": member.date_of_birth.strftime("%Y-%m-%d") if member.date_of_birth else "--",
        "biometric_id": getattr(member, "biometric_id", "") or "--",
        "join_date": member.join_date.strftime("%Y-%m-%d"),
        "expiry_date": member.membership_end_date.strftime("%d-%b-%Y") if member.membership_end_date else "--",
        "height": member.height or "--",
        "weight": member.weight or "--",
        "bmi": bmi_str,
        "fitness_goal": member.fitness_goal or "General Fitness",
        "medical_condition": member.medical_condition or "None",
        "plan": plan.name if plan else "General Plan",
        "plan_amount": f"{plan_amount:.2f}",
        "amount_paid": f"{amount_paid:.2f}",
        "remaining_amount": f"{remaining_amount:.2f}",
        "joined_since": joined_since,
        "total_visits": total_visits,
        "last_visit": last_visit,
        "checkin_today": checkin_today,
        "duration_inside": duration_inside,
        "month_visits": f"{month_visits} visits",
        "total_attendance": f"{total_visits} visits",
    }


def build_trainer_detail_payload(trainer):
    """Build the trainer profile + attendance-summary dict shown by the shared
    detail popup in trainer mode. Single source of truth mirroring
    ``build_member_detail_payload`` for trainers."""
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

    return {
        "id": trainer.trainer_id,
        "name": trainer.full_name,
        "photo_url": photo_url,
        "status": trainer.get_working_status_display() if hasattr(trainer, "get_working_status_display") else trainer.working_status,
        "gender": trainer.get_gender_display() or "Male",
        "blood_group": trainer.blood_group or "--",
        "mobile": trainer.mobile_number,
        "email": trainer.email or "--",
        "username": getattr(trainer, "username", "") or "--",
        "address": trainer.address or "--",
        "dob": trainer.date_of_birth.strftime("%Y-%m-%d") if trainer.date_of_birth else "--",
        "biometric_id": getattr(trainer, "biometric_id", "") or "--",
        "join_date": trainer.joining_date.strftime("%Y-%m-%d"),
        "designation": trainer.get_designation_display() if hasattr(trainer, "get_designation_display") else trainer.designation,
        "working_status": trainer.get_working_status_display() if hasattr(trainer, "get_working_status_display") else trainer.working_status,
        "working_time": trainer.working_time or "--",
        "salary": str(trainer.salary) if trainer.salary else "--",
        "joined_since": f"Since {trainer.joining_date.strftime('%b %Y')}",
        "total_visits": total_visits,
        "last_visit": last_visit,
        "checkin_today": checkin_today,
        "duration_inside": duration_inside,
        "month_visits": f"{month_visits} days",
        "total_attendance": f"{total_visits} days",
    }
