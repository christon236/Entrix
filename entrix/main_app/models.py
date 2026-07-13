import uuid
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from masters.models import MembershipPlan

phone_validator = RegexValidator(
    regex=r'^\+?[0-9]+$',
    message='Only numbers (0-9) and optional leading plus (+) are allowed.'
)
 

 
 
class Member(models.Model):
    """
    A registered gym member.
    """
 
    GENDER_MALE = "M"
    GENDER_FEMALE = "F"
    GENDER_OTHER = "O"
    GENDER_CHOICES = (
        (GENDER_MALE, "Male"),
        (GENDER_FEMALE, "Female"),
        (GENDER_OTHER, "Other"),
    )
 
    member_id = models.CharField(max_length=20, unique=True, blank=True, editable=False)
    full_name = models.CharField(max_length=150)
    mobile_number = models.CharField(max_length=15, validators=[phone_validator])
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    emergency_contact = models.CharField(max_length=15, blank=True, validators=[phone_validator])
    photo = models.ImageField(upload_to="members/photos/", blank=True, null=True)
    fingerprint_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    blood_group = models.CharField(max_length=5, blank=True, default="")
    height = models.CharField(max_length=20, blank=True, default="")
    weight = models.CharField(max_length=20, blank=True, default="")
    fitness_goal = models.CharField(max_length=100, blank=True, default="")
    medical_condition = models.CharField(max_length=255, blank=True, default="")
 
    membership_plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
    )
    join_date = models.DateField(default=timezone.now)
    membership_start_date = models.DateField(default=timezone.now)
    membership_end_date = models.DateField()
    is_active = models.BooleanField(default=True)
 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering = ["-created_at"]
 
    def __str__(self):
        return f"{self.member_id} - {self.full_name}"
 
    def save(self, *args, **kwargs):
        if not self.member_id:
            self.member_id = f"ENTRIX-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)
 
    @property
    def is_expired(self):
        return self.membership_end_date < timezone.now().date()
 
    @property
    def days_remaining(self):
        delta = self.membership_end_date - timezone.now().date()
        return delta.days
 
 
class Attendance(models.Model):
    """
    A single entry/exit record for a member on a given day.
    Created automatically by the fingerprint access flow (future module).
    """
 
    STATUS_INSIDE = "inside"
    STATUS_CHECKED_OUT = "checked_out"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = (
        (STATUS_INSIDE, "Inside"),
        (STATUS_CHECKED_OUT, "Checked Out"),
        (STATUS_EXPIRED, "Expired"),
    )
 
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="attendance_records"
    )
    date = models.DateField(default=timezone.now)
    entry_time = models.TimeField(null=True, blank=True)
    exit_time = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_INSIDE)
    fingerprint_id = models.CharField(max_length=50, null=True, blank=True)
    entry_allowed = models.BooleanField(default=True)
    membership_status_at_entry = models.CharField(max_length=20, default="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.CharField(max_length=255, blank=True)
 
    class Meta:
        ordering = ["-date", "-entry_time"]
 
    def __str__(self):
        return f"{self.member.full_name} - {self.date}"
 
    @property
    def duration(self):
        """Returns a formatted duration string, or None if the member hasn't exited yet."""
        if self.entry_time and self.exit_time:
            today = timezone.now().date()
            entry_dt = timezone.datetime.combine(today, self.entry_time)
            exit_dt = timezone.datetime.combine(today, self.exit_time)
            seconds = (exit_dt - entry_dt).total_seconds()
            if seconds < 0:
                return None
            hours, remainder = divmod(int(seconds), 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{hours}h {minutes}m"
        return None


class AttendanceVisit(models.Model):
    """
    Child model representing individual entry/exit visits for a member on a specific day.
    Normalizes multiple check-ins/check-outs under a single daily Attendance parent record.
    """
    attendance = models.ForeignKey(
        Attendance, on_delete=models.CASCADE, related_name="visits"
    )
    visit_number = models.PositiveIntegerField(default=1)
    entry_time = models.TimeField(null=True, blank=True)
    exit_time = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["visit_number"]

    def __str__(self):
        return f"{self.attendance} - Visit #{self.visit_number}"

    @property
    def visit_label(self):
        if self.visit_number == 1:
            return "1st Time"
        elif self.visit_number == 2:
            return "2nd Time"
        elif self.visit_number == 3:
            return "3rd Time"
        else:
            return f"{self.visit_number}th Time"

    @property
    def duration_str(self):
        if self.entry_time and self.exit_time:
            today = timezone.now().date()
            if hasattr(self.attendance, "date") and self.attendance.date:
                today = self.attendance.date
            entry_dt = timezone.datetime.combine(today, self.entry_time)
            exit_dt = timezone.datetime.combine(today, self.exit_time)
            seconds = (exit_dt - entry_dt).total_seconds()
            if seconds < 0:
                return None
            hours, remainder = divmod(int(seconds), 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        elif self.entry_time and not self.exit_time:
            today = timezone.localdate()
            if hasattr(self.attendance, "date") and self.attendance.date == today:
                now_time = timezone.localtime().time()
                entry_dt = timezone.datetime.combine(today, self.entry_time)
                now_dt = timezone.datetime.combine(today, now_time)
                seconds = (now_dt - entry_dt).total_seconds()
                if seconds > 0:
                    hours, remainder = divmod(int(seconds), 3600)
                    minutes, _ = divmod(remainder, 60)
                    return f"{hours}h {minutes}m (Active)" if hours > 0 else f"{minutes}m (Active)"
        return None


class TrainerAttendance(models.Model):
    """
    A single entry/exit parent record for a Trainer on a given day.
    Normalizes multiple daily check-ins/check-outs under one parent record per trainer per day.
    """
    STATUS_INSIDE = "inside"
    STATUS_CHECKED_OUT = "checked_out"
    STATUS_CHOICES = (
        (STATUS_INSIDE, "Inside"),
        (STATUS_CHECKED_OUT, "Checked Out"),
    )

    trainer = models.ForeignKey(
        'masters.Trainer', on_delete=models.CASCADE, related_name="trainer_attendance_records"
    )
    date = models.DateField(default=timezone.now)
    entry_time = models.TimeField(null=True, blank=True)
    exit_time = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_INSIDE)
    fingerprint_id = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-date", "-entry_time"]

    def __str__(self):
        return f"{self.trainer.full_name} - {self.date}"

    @property
    def duration(self):
        if self.entry_time and self.exit_time:
            today = timezone.now().date()
            if self.date:
                today = self.date
            entry_dt = timezone.datetime.combine(today, self.entry_time)
            exit_dt = timezone.datetime.combine(today, self.exit_time)
            seconds = (exit_dt - entry_dt).total_seconds()
            if seconds < 0:
                return None
            hours, remainder = divmod(int(seconds), 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        return None


class TrainerAttendanceVisit(models.Model):
    """
    Child model representing individual entry/exit visits for a Trainer on a specific day.
    Normalizes multiple check-ins/check-outs under a single daily TrainerAttendance parent record.
    """
    attendance = models.ForeignKey(
        TrainerAttendance, on_delete=models.CASCADE, related_name="visits"
    )
    visit_number = models.PositiveIntegerField(default=1)
    entry_time = models.TimeField(null=True, blank=True)
    exit_time = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["visit_number"]

    def __str__(self):
        return f"{self.attendance} - Visit #{self.visit_number}"

    @property
    def visit_label(self):
        if self.visit_number == 1:
            return "1st Time"
        elif self.visit_number == 2:
            return "2nd Time"
        elif self.visit_number == 3:
            return "3rd Time"
        else:
            return f"{self.visit_number}th Time"

    @property
    def duration_str(self):
        if self.entry_time and self.exit_time:
            today = timezone.now().date()
            if hasattr(self.attendance, "date") and self.attendance.date:
                today = self.attendance.date
            entry_dt = timezone.datetime.combine(today, self.entry_time)
            exit_dt = timezone.datetime.combine(today, self.exit_time)
            seconds = (exit_dt - entry_dt).total_seconds()
            if seconds < 0:
                return None
            hours, remainder = divmod(int(seconds), 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        elif self.entry_time and not self.exit_time:
            today = timezone.localdate()
            if hasattr(self.attendance, "date") and self.attendance.date == today:
                now_time = timezone.localtime().time()
                entry_dt = timezone.datetime.combine(today, self.entry_time)
                now_dt = timezone.datetime.combine(today, now_time)
                seconds = (now_dt - entry_dt).total_seconds()
                if seconds > 0:
                    hours, remainder = divmod(int(seconds), 3600)
                    minutes, _ = divmod(remainder, 60)
                    return f"{hours}h {minutes}m (Active)" if hours > 0 else f"{minutes}m (Active)"
        return None


class GymProfile(models.Model):
    """
    Singleton model storing gym information, contact details, and working hours JSON.
    """
    name = models.CharField("Gym Name", max_length=150, default="")
    logo = models.ImageField("Gym Logo", upload_to="gym/logos/", null=True, blank=True)
    address = models.TextField("Address", default="")
    contact_number = models.CharField("Contact Number", max_length=25, default="", validators=[phone_validator])
    alternate_contact = models.CharField("Alternate Contact", max_length=25, blank=True, default="", validators=[phone_validator])
    email = models.EmailField("Email Address", default="")
    max_occupancy = models.PositiveIntegerField("Max Occupancy", default=0, null=True, blank=True)
    schedule_json = models.TextField(
        "Working Schedule JSON",
        blank=True,
        default='[{"id":1,"days":["Mon","Tue","Wed","Thu","Fri","Sat"],"type":"open","slots":[{"start":"05:00","end":"22:00"}]},{"id":2,"days":["Sun"],"type":"open","slots":[{"start":"06:00","end":"20:00"}]}]'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Gym Profile"
        verbose_name_plural = "Gym Profile"

    def __str__(self):
        return self.name

    @classmethod
    def get_instance(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


class AdminProfile(models.Model):
    """
    Extends Django's User model with gym administrator profile information.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="admin_profile"
    )
    photo = models.ImageField("Admin Photo", upload_to="admin/photos/", null=True, blank=True)
    mobile_number = models.CharField("Mobile Number", max_length=20, blank=True, default="", validators=[phone_validator])
    designation = models.CharField("Designation", max_length=100, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Admin Profile"
        verbose_name_plural = "Admin Profiles"

    def __str__(self):
        return f"{self.user.get_username()} - {self.designation}"