import random
import string
import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


# =============================================================================
# Shared helpers
# =============================================================================

def generate_unique_numeric_code(model_cls, field_name, length=6):
    """
    Generates a unique, system-generated numeric PIN/code for the given model
    and field (used for Biometric IDs). Retries on the rare collision.

    This is the single source of truth for Biometric ID generation across
    Members and Trainers, so the format stays consistent everywhere.
    """
    while True:
        code = "".join(random.choices(string.digits, k=length))
        if not model_cls.objects.filter(**{field_name: code}).exists():
            return code


phone_validator = RegexValidator(
    regex=r"^\+?[0-9]+$",
    message="Enter a valid mobile number using digits (0-9) and optional leading plus (+) symbol only (up to 15 digits).",
)


# =============================================================================
# Membership Plan
# =============================================================================

class MembershipPlan(models.Model):

    DURATION_DAYS = "days"
    DURATION_WEEKS = "weeks"
    DURATION_MONTHS = "months"
    DURATION_YEARS = "years"
    DURATION_TYPE_CHOICES = (
        (DURATION_DAYS, "Days"),
        (DURATION_WEEKS, "Weeks"),
        (DURATION_MONTHS, "Months"),
        (DURATION_YEARS, "Years"),
    )

    ACCESS_GENERAL = "general"
    ACCESS_PREMIUM = "premium"
    ACCESS_VIP = "vip"
    ACCESS_TYPE_CHOICES = (
        (ACCESS_GENERAL, "General Access"),
        (ACCESS_PREMIUM, "Premium Access"),
        (ACCESS_VIP, "VIP Access — 24/7"),
    )

    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_DRAFT = "draft"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_DRAFT, "Draft"),
    )

    name = models.CharField("Plan Name", max_length=100, unique=True)
    plan_code = models.CharField(
        "Plan Code", max_length=20, unique=True, blank=True, editable=False
    )
    description = models.TextField("Description", blank=True)

    duration = models.PositiveIntegerField(
        "Duration", validators=[MinValueValidator(1)]
    )
    duration_type = models.CharField(
        "Duration Type", max_length=10, choices=DURATION_TYPE_CHOICES, default=DURATION_MONTHS
    )

    price = models.DecimalField(
        "Price", max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    joining_fee = models.DecimalField(
        "Joining Fee",
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    max_freeze_days = models.PositiveIntegerField(
        "Maximum Freeze Days", default=0, validators=[MinValueValidator(0)]
    )

    daily_access_hours = models.PositiveIntegerField(
        "Daily Access Limit (Hours)",
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(24)],
        help_text="Number of hours per day a member on this plan may access the gym, "
                   "set by the admin. Use 24 for unrestricted / 24x7 access.",
    )

    access_type = models.CharField(
        "Access Type", max_length=10, choices=ACCESS_TYPE_CHOICES, default=ACCESS_GENERAL
    )
    status = models.CharField(
        "Plan Status", max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )
    display_order = models.PositiveIntegerField(
        "Display Order", default=0, validators=[MinValueValidator(0)]
    )

    is_active = models.BooleanField("Is Active", default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_plans",
    )
    created_at = models.DateTimeField("Created Date", auto_now_add=True)
    updated_at = models.DateTimeField("Updated Date", auto_now=True)

    class Meta:
        ordering = ["display_order", "price"]
        verbose_name = "Membership Plan"
        verbose_name_plural = "Membership Plans"

    def __str__(self):
        return f"{self.plan_code} - {self.name}"

    def clean(self):
        errors = {}
        if self.price is not None and self.price < 0:
            errors["price"] = "Price cannot be negative."
        if self.duration is not None and self.duration <= 0:
            errors["duration"] = "Duration must be greater than zero."
        if self.joining_fee is not None and self.joining_fee < 0:
            errors["joining_fee"] = "Joining fee cannot be negative."
        if self.display_order is not None and self.display_order < 0:
            errors["display_order"] = "Display order cannot be negative."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.is_active = self.status == self.STATUS_ACTIVE

        is_new = self._state.adding
        super().save(*args, **kwargs)

        if is_new and not self.plan_code:
            self.plan_code = f"PLN-{self.pk:04d}"
            super().save(update_fields=["plan_code"])

    @property
    def final_price(self):
        return self.price

    @property
    def is_premium(self):
        return self.access_type in (self.ACCESS_PREMIUM, self.ACCESS_VIP)

    @property
    def is_full_day_access(self):
        return self.daily_access_hours >= 24

    @property
    def access_hours_display(self):
        if self.is_full_day_access:
            return "24/7 Access"
        return f"{self.daily_access_hours} hrs/day"

    @property
    def duration_in_days(self):
        if not self.duration:
            return 1
        if self.duration_type == self.DURATION_DAYS:
            return self.duration
        elif self.duration_type == self.DURATION_WEEKS:
            return self.duration * 7
        elif self.duration_type == self.DURATION_MONTHS:
            return self.duration * 30
        elif self.duration_type == self.DURATION_YEARS:
            return self.duration * 365
        return self.duration * 30

    @property
    def daily_access_value(self):
        days = self.duration_in_days
        if days > 0 and self.final_price:
            return round(self.final_price / days, 2)
        return 0

    @property
    def member_count(self):
        return self.members.count()


# =============================================================================
# Access Type Master (Change 3)
# =============================================================================

class AccessType(models.Model):
    """
    Master table for Membership Plan Access Types.

    Replaces the hardcoded ACCESS_TYPE_CHOICES on MembershipPlan.
    The `slug` field must match the values already stored in
    MembershipPlan.access_type (e.g. 'general', 'premium', 'vip') so that
    existing plans are never orphaned during the transition.

    New access types can be added at runtime from the "Access Type Master"
    modal in Membership Plans — without any code change.
    """

    # Slugs for the built-in defaults (kept as constants for code referencing)
    SLUG_GENERAL = "general"
    SLUG_PREMIUM = "premium"
    SLUG_VIP = "vip"

    slug = models.SlugField(
        "Slug", max_length=30, unique=True,
        help_text="Unique identifier stored in MembershipPlan.access_type (lowercase, no spaces).",
    )
    name = models.CharField("Display Name", max_length=60, unique=True)
    description = models.CharField(
        "Description", max_length=200, blank=True,
        help_text="Short description shown in the membership plan form.",
    )
    icon = models.CharField(
        "Bootstrap Icon", max_length=60, blank=True, default="bi-door-open",
        help_text="Bootstrap Icon class, e.g. bi-gem, bi-star-fill.",
    )
    is_active = models.BooleanField("Is Active", default=True)
    display_order = models.PositiveSmallIntegerField("Display Order", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name = "Access Type"
        verbose_name_plural = "Access Types"

    def __str__(self):
        return self.name

    @property
    def is_used(self):
        """True if any MembershipPlan currently uses this access type slug."""
        return MembershipPlan.objects.filter(access_type=self.slug).exists()

    # Default access types (mirrors the original hardcoded choices).
    DEFAULTS = [
        {"slug": SLUG_GENERAL,  "name": "General Access",      "icon": "bi-door-open",     "display_order": 1},
        {"slug": SLUG_PREMIUM,  "name": "Premium Access",      "icon": "bi-award-fill",    "display_order": 2},
        {"slug": SLUG_VIP,      "name": "VIP Access — 24/7",   "icon": "bi-gem",          "display_order": 3},
    ]

    @classmethod
    def ensure_defaults(cls):
        """Idempotently seeds the default access types. Safe to call anytime."""
        for row in cls.DEFAULTS:
            cls.objects.get_or_create(
                slug=row["slug"],
                defaults={
                    "name": row["name"],
                    "icon": row["icon"],
                    "display_order": row["display_order"],
                },
            )


# =============================================================================
# Trainer Designation Master (item 11 — "Manage Designations" popup)
# =============================================================================

class TrainerDesignation(models.Model):

    """
    Master list of trainer designations/roles. Populated with the original
    default roles via a data migration, and can be extended at runtime from
    the 'Manage Designations' popup next to the Designation field in the
    Trainer Registration Wizard — without requiring a code change.
    """

    name = models.CharField("Designation", max_length=60, unique=True)
    is_active = models.BooleanField("Is Active", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Trainer Designation"
        verbose_name_plural = "Trainer Designations"

    def __str__(self):
        return self.name

    @property
    def is_used(self):
        # Using a string lookup on Trainer model because designation is stored as a CharField on Trainer
        from masters.models import Trainer
        return Trainer.objects.filter(designation=self.name).exists()

    DEFAULTS = (
        "Head Trainer",
        "Fitness Trainer",
        "Yoga Instructor",
        "Zumba Instructor",
        "Nutrition Coach",
        "Physiotherapist",
    )

    @classmethod
    def ensure_defaults(cls):
        """Idempotently seeds the default designations. Safe to call anytime."""
        for name in cls.DEFAULTS:
            cls.objects.get_or_create(name=name)


# =============================================================================
# Trainer
# =============================================================================

class Trainer(models.Model):
    """
    A gym fitness trainer or instructor registered in ENTRIX.

    Biometric handling: the standalone biometric-device wizard/step has been
    removed. A `biometric_id` PIN is now generated automatically and silently
    on registration (see `save()`), and is only *displayed* — never captured —
    inside the Basic Information section of the wizard/edit views.
    """

    GENDER_MALE = "Male"
    GENDER_FEMALE = "Female"
    GENDER_OTHER = "Other"
    GENDER_CHOICES = (
        (GENDER_MALE, "Male"),
        (GENDER_FEMALE, "Female"),
        (GENDER_OTHER, "Other"),
    )

    STATUS_PERMANENT = "Permanent"
    STATUS_PART_TIME = "Part Time"
    STATUS_LEFT = "Left" # Legacy
    STATUS_CHOICES = (
        (STATUS_PERMANENT, "Permanent"),
        (STATUS_PART_TIME, "Part Time"),
    )

    trainer_id = models.CharField("Trainer ID", max_length=20, unique=True, blank=True, editable=False)
    full_name = models.CharField("Trainer Name", max_length=150)
    gender = models.CharField("Gender", max_length=15, choices=GENDER_CHOICES, default=GENDER_MALE)
    mobile_number = models.CharField(
        "Mobile Number", max_length=15, validators=[phone_validator]
    )
    email = models.EmailField("Email", blank=True, null=True)
    date_of_birth = models.DateField("Date of Birth", null=True, blank=True)
    blood_group = models.CharField("Blood Group", max_length=5, blank=True, default="")
    address = models.TextField("Address", blank=True)
    photo = models.ImageField("Photo", upload_to="trainers/photos/", blank=True, null=True)

    designation = models.CharField("Designation", max_length=60, default="Fitness Trainer")
    joining_date = models.DateField("Joining Date", default=timezone.localdate)
    salary = models.DecimalField("Salary (₹ / month)", max_digits=10, decimal_places=2, null=True, blank=True)
    working_status = models.CharField("Working Status", max_length=20, choices=STATUS_CHOICES, default=STATUS_PERMANENT)
    working_time = models.CharField("Working Time", max_length=50, blank=True, default="06:00 - 14:00")

    # ---- Biometric ID (system generated, replaces the old device capture) ----
    biometric_id = models.CharField(
        "Biometric ID", max_length=6, unique=True, blank=True, editable=False,
        help_text="System-generated 6-digit PIN. Used later for biometric device / API integration.",
    )

    # ---- Login credentials (item 4) — optional, for future login use.
    # null=True (not just blank=True) so multiple trainers can be left
    # without a username without tripping the unique constraint — SQL
    # treats each NULL as distinct, but two empty strings '' would collide.
    username = models.CharField("Username", max_length=40, unique=True, blank=True, null=True)
    password_pin = models.CharField(
        "Password (hashed)", max_length=128, blank=True, null=True,
        help_text="Stored as a salted hash of the 4-digit PIN entered at registration. "
                   "Left blank until a login is set up.",
    )

    created_at = models.DateTimeField("Created Date", auto_now_add=True)
    updated_at = models.DateTimeField("Updated Date", auto_now=True)

    class Meta:
        ordering = ["-joining_date", "full_name"]
        verbose_name = "Trainer"
        verbose_name_plural = "Trainers"

    def __str__(self):
        return f"{self.trainer_id} - {self.full_name} ({self.designation})"

    def set_pin(self, raw_pin):
        """Hash and store a raw 4-digit PIN. Call this instead of assigning password_pin directly."""
        self.password_pin = make_password(raw_pin)

    def check_pin(self, raw_pin):
        if not self.password_pin:
            return False
        return check_password(raw_pin, self.password_pin)

    @property
    def is_active(self):
        """Used by the Active/Inactive status capsule in the Trainers Directory."""
        return self.working_status in (self.STATUS_PERMANENT, self.STATUS_PART_TIME, "Working")

    @property
    def age(self):
        """Age in whole years derived from ``date_of_birth`` (None if unset)."""
        if not self.date_of_birth:
            return None
        today = timezone.now().date()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )

    def save(self, *args, **kwargs):
        if not self.trainer_id:
            self.trainer_id = f"TRN-{uuid.uuid4().hex[:6].upper()}"
        if not self.biometric_id:
            self.biometric_id = generate_unique_numeric_code(Trainer, "biometric_id", length=6)
        # A blank username must be stored as NULL, never "" — otherwise a
        # second blank trainer would collide on the unique constraint and
        # wrongly report the username as already taken.
        if not (self.username or "").strip():
            self.username = None
        super().save(*args, **kwargs)

    # -------------------------------------------------------------------
    # API INTEGRATION POINT
    # -------------------------------------------------------------------
    # Future biometric-device / third-party API sync (e.g. pushing the
    # generated `biometric_id` to a turnstile / attendance device) should be
    # implemented here or triggered from a post_save signal on this model.
    # Do NOT re-introduce device-capture fields on the model — the device
    # only ever needs to be told the `biometric_id` that already exists.
    # -------------------------------------------------------------------