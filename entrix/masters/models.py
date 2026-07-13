
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

phone_validator = RegexValidator(
    regex=r'^\+?[0-9]+$',
    message='Only numbers (0-9) and optional leading plus (+) are allowed.'
)
 
 
class MembershipPlan(models.Model):
    """
    A purchasable gym membership plan (Monthly, Quarterly, VIP, etc).
    Lives in the `master` app per project architecture — all master-data
    modules (plans, categories, equipment, etc.) belong here, not in main_app.
    """
 
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
    discount_percentage = models.DecimalField(
        "Discount (%)",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
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
        if self.discount_percentage is not None and self.discount_percentage > 100:
            errors["discount_percentage"] = "Discount cannot exceed 100%."
        if self.joining_fee is not None and self.joining_fee < 0:
            errors["joining_fee"] = "Joining fee cannot be negative."
        if self.display_order is not None and self.display_order < 0:
            errors["display_order"] = "Display order cannot be negative."
        if errors:
            raise ValidationError(errors)
 
    def save(self, *args, **kwargs):
        # Keep is_active in sync with the status field
        self.is_active = self.status == self.STATUS_ACTIVE
 
        is_new = self._state.adding
        super().save(*args, **kwargs)
 
        if is_new and not self.plan_code:
            self.plan_code = f"PLN-{self.pk:04d}"
            super().save(update_fields=["plan_code"])
 
    @property
    def final_price(self):
        """Price after discount is applied."""
        if self.discount_percentage:
            discount_amount = (self.price * self.discount_percentage) / 100
            return self.price - discount_amount
        return self.price
 
    @property
    def is_premium(self):
        return self.access_type in (self.ACCESS_PREMIUM, self.ACCESS_VIP)
 
    @property
    def member_count(self):
        """Number of members currently assigned this plan."""
        return self.members.count()


class Trainer(models.Model):
    """
    A gym fitness trainer or instructor registered in ENTRIX.
    Belongs in the master app alongside other entity registries.
    Matches all employment, basic, and biometric fields from the Trainer Registration Wizard.
    """

    GENDER_MALE = "Male"
    GENDER_FEMALE = "Female"
    GENDER_OTHER = "Other"
    GENDER_CHOICES = (
        (GENDER_MALE, "Male"),
        (GENDER_FEMALE, "Female"),
        (GENDER_OTHER, "Other"),
    )

    STATUS_WORKING = "Working"
    STATUS_ON_LEAVE = "On Leave"
    STATUS_LEFT = "Left"
    STATUS_CHOICES = (
        (STATUS_WORKING, "Working"),
        (STATUS_ON_LEAVE, "On Leave"),
        (STATUS_LEFT, "Left"),
    )

    DESIGNATION_HEAD = "Head Trainer"
    DESIGNATION_FITNESS = "Fitness Trainer"
    DESIGNATION_YOGA = "Yoga Instructor"
    DESIGNATION_ZUMBA = "Zumba Instructor"
    DESIGNATION_NUTRITION = "Nutrition Coach"
    DESIGNATION_PHYSIO = "Physiotherapist"
    DESIGNATION_CHOICES = (
        (DESIGNATION_HEAD, "Head Trainer"),
        (DESIGNATION_FITNESS, "Fitness Trainer"),
        (DESIGNATION_YOGA, "Yoga Instructor"),
        (DESIGNATION_ZUMBA, "Zumba Instructor"),
        (DESIGNATION_NUTRITION, "Nutrition Coach"),
        (DESIGNATION_PHYSIO, "Physiotherapist"),
    )

    trainer_id = models.CharField("Trainer ID", max_length=20, unique=True, blank=True, editable=False)
    full_name = models.CharField("Trainer Name", max_length=150)
    gender = models.CharField("Gender", max_length=15, choices=GENDER_CHOICES, default=GENDER_MALE)
    mobile_number = models.CharField("Mobile Number", max_length=15, validators=[phone_validator])
    address = models.TextField("Address", blank=True)
    photo = models.ImageField("Photo", upload_to="trainers/photos/", blank=True, null=True)

    designation = models.CharField("Designation", max_length=50, choices=DESIGNATION_CHOICES, default=DESIGNATION_FITNESS)
    joining_date = models.DateField("Joining Date", default=timezone.now)
    salary = models.DecimalField("Salary (₹ / month)", max_digits=10, decimal_places=2, null=True, blank=True)
    working_status = models.CharField("Working Status", max_length=20, choices=STATUS_CHOICES, default=STATUS_WORKING)
    working_time = models.CharField("Working Time", max_length=50, blank=True, default="")

    fingerprint_id = models.CharField("Fingerprint ID", max_length=50, unique=True, blank=True, null=True)

    created_at = models.DateTimeField("Created Date", auto_now_add=True)
    updated_at = models.DateTimeField("Updated Date", auto_now=True)

    class Meta:
        ordering = ["-joining_date", "full_name"]
        verbose_name = "Trainer"
        verbose_name_plural = "Trainers"

    def __str__(self):
        return f"{self.trainer_id} - {self.full_name} ({self.designation})"

    def save(self, *args, **kwargs):
        if not self.trainer_id:
            self.trainer_id = f"TRN-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

 