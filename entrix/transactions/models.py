from django.db import models
from django.utils import timezone
from main_app.models import Member


class AttendanceLog(models.Model):
    """
    Immutable access control log recording every turnstile attempt, tap, or scan.
    Tracks successful check-ins, check-outs, and access denials (e.g. expired membership,
    unrecognized fingerprint ID).
    """

    EVENT_CHECKIN = "check_in"
    EVENT_CHECKOUT = "check_out"
    EVENT_DENIED_EXPIRED = "denied_expired"
    EVENT_DENIED_UNKNOWN = "denied_unknown"
    EVENT_CHOICES = (
        (EVENT_CHECKIN, "Check-in Granted"),
        (EVENT_CHECKOUT, "Check-out Recorded"),
        (EVENT_DENIED_EXPIRED, "Access Denied - Expired Membership"),
        (EVENT_DENIED_UNKNOWN, "Access Denied - Unrecognized Fingerprint"),
    )

    member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_logs",
        help_text="Associated gym member if fingerprint ID was recognized.",
    )
    fingerprint_id = models.CharField(
        "Fingerprint ID",
        max_length=50,
        blank=True,
        help_text="Raw fingerprint ID scanned at the turnstile.",
    )
    event_type = models.CharField(
        "Event Type", max_length=25, choices=EVENT_CHOICES, default=EVENT_CHECKIN
    )
    timestamp = models.DateTimeField("Timestamp", default=timezone.now)
    entry_allowed = models.BooleanField("Entry Allowed", default=True)
    reason = models.CharField(
        "Reason / Notes",
        max_length=255,
        blank=True,
        help_text="Explanation for denial or additional system notes.",
    )

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Attendance Log"
        verbose_name_plural = "Attendance Logs"

    def __str__(self):
        member_name = self.member.full_name if self.member else f"Unknown ({self.fingerprint_id})"
        return f"{member_name} - {self.get_event_type_display()} @ {self.timestamp.strftime('%H:%M:%S')}"


class AttendanceSummary(models.Model):
    """
    Aggregated daily and monthly attendance statistics per member.
    Used for rapid reporting, charting, and dashboard metrics without querying raw logs.
    """

    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="attendance_summaries",
    )
    date = models.DateField("Summary Date", default=timezone.localdate)
    total_duration_minutes = models.PositiveIntegerField("Total Duration (Mins)", default=0)
    checkin_count = models.PositiveIntegerField("Check-ins Today", default=0)
    month_attendance_count = models.PositiveIntegerField("This Month Visits", default=0)
    total_attendance_count = models.PositiveIntegerField("Total Lifetime Visits", default=0)
    updated_at = models.DateTimeField("Last Updated", auto_now=True)

    class Meta:
        ordering = ["-date", "member"]
        unique_together = ("member", "date")
        verbose_name = "Attendance Summary"
        verbose_name_plural = "Attendance Summaries"

    def __str__(self):
        return f"{self.member.full_name} - {self.date} ({self.total_duration_minutes} mins)"

    @property
    def formatted_duration(self):
        """Returns duration formatted as hours and minutes (e.g. 2h 15m)."""
        if self.total_duration_minutes <= 0:
            return "0m"
        hours, mins = divmod(self.total_duration_minutes, 60)
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"


class Occupancy(models.Model):
    """
    Daily gym capacity and real-time occupancy tracking.
    """

    date = models.DateField("Date", default=timezone.localdate, unique=True)
    current_inside = models.PositiveIntegerField("Currently Inside", default=0)
    peak_occupancy = models.PositiveIntegerField("Peak Occupancy Today", default=0)
    max_capacity = models.PositiveIntegerField("Maximum Gym Capacity", default=100)
    updated_at = models.DateTimeField("Last Updated", auto_now=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "Occupancy Record"
        verbose_name_plural = "Occupancy Records"

    def __str__(self):
        return f"Occupancy on {self.date}: {self.current_inside}/{self.max_capacity} (Peak: {self.peak_occupancy})"

    @property
    def occupancy_percentage(self):
        """Returns percentage of current capacity filled."""
        if self.max_capacity <= 0:
            return 0
        return round((self.current_inside / self.max_capacity) * 100, 1)
