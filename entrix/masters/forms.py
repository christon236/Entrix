import re

from django import forms
from django.contrib.auth.hashers import make_password
from django.core.validators import RegexValidator

from main_app.models import Member
from .models import AccessType, MembershipPlan, Trainer, TrainerDesignation

# ---------------------------------------------------------------------------
# Shared validators (item 5)
# ---------------------------------------------------------------------------

PHONE_REGEX = re.compile(r"^\+?[0-9]+$")

phone_form_validator = RegexValidator(
    regex=r"^\+?[0-9]+$",
    message="Mobile number must contain digits (0-9) and optional leading plus (+) symbol only.",
)

PIN_REGEX = re.compile(r"^[0-9]{4}$")

BLOOD_GROUP_CHOICES = [
    ("", "Select blood group..."),
    ("O+", "O+"),
    ("O-", "O-"),
    ("A+", "A+"),
    ("A-", "A-"),
    ("B+", "B+"),
    ("B-", "B-"),
    ("AB+", "AB+"),
    ("AB-", "AB-"),
]


class MembershipPlanForm(forms.ModelForm):
    """
    Shared Add/Edit form for the Membership Plans modal.
    Used by MembershipPlanView for both create and update POST actions.
    """

    class Meta:
        model = MembershipPlan
        fields = [
            "name",
            "description",
            "duration",
            "duration_type",
            "price",
            "daily_access_hours",
            "access_type",
            "status",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control entrix-input",
                    "placeholder": "Enter plan name",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control entrix-input",
                    "rows": 3,
                    "placeholder": "Short description shown to members during registration",
                }
            ),
            "duration": forms.NumberInput(
                attrs={"class": "form-control entrix-input", "placeholder": "Enter duration of the plan", "min": 1}
            ),
            "duration_type": forms.Select(attrs={"class": "form-select entrix-input"}),
            "price": forms.NumberInput(
                attrs={"class": "form-control entrix-input", "placeholder": "Enter price", "min": 0, "step": "0.01"}
            ),
            "daily_access_hours": forms.NumberInput(
                attrs={"class": "form-control entrix-input", "placeholder": "Enter hours allowed per day", "min": 1, "max": 24}
            ),
            "access_type": forms.Select(attrs={"class": "form-select entrix-input"}),
            "status": forms.Select(attrs={"class": "form-select entrix-input"}),
        }
        help_texts = {
            "price": "Base price for this membership plan.",
            "daily_access_hours": "Hours per day a member can access the gym on this plan. Use 24 for 24x7 access.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Change 3 — Populate access_type choices from the AccessType master
        # table instead of hardcoded choices. Falls back gracefully.
        try:
            dynamic_choices = [
                (at.slug, at.name)
                for at in AccessType.objects.filter(is_active=True).order_by("display_order", "name")
            ]
            if dynamic_choices:
                self.fields["access_type"].choices = [("", "Select access type...")] + dynamic_choices
        except Exception:
            # Table may not exist yet (first migration) — keep hardcoded choices.
            pass

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = MembershipPlan.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A plan with this name already exists.")
        return name

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price < 0:
            raise forms.ValidationError("Price cannot be negative.")
        return price

    def clean_duration(self):
        duration = self.cleaned_data["duration"]
        if duration <= 0:
            raise forms.ValidationError("Duration must be greater than zero.")
        return duration

    def clean_joining_fee(self):
        joining_fee = self.cleaned_data["joining_fee"]
        if joining_fee < 0:
            raise forms.ValidationError("Joining fee cannot be negative.")
        return joining_fee

    def clean_daily_access_hours(self):
        hours = self.cleaned_data["daily_access_hours"]
        if hours < 1 or hours > 24:
            raise forms.ValidationError("Daily access limit must be between 1 and 24 hours.")
        return hours


# ---------------------------------------------------------------------------
# Shared mixin: login credentials (item 4) + phone/email validation (item 5)
# ---------------------------------------------------------------------------

class LoginCredentialsMixin(forms.ModelForm):
    """
    Adds Username + 4-digit PIN password fields to a registration form.
    The raw PIN is never stored directly — `save()` hashes it onto
    `instance.password_pin` via `set_pin()` (defined on both Member and
    Trainer models).
    """

    # Login credentials are for future use only — never required to
    # register a member/trainer. Leaving either blank simply means no
    # login is set up yet (on edit, it means "keep the existing value").
    username = forms.CharField(
        max_length=40,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control entrix-input",
            "placeholder": "Login username (optional — for future use)",
            "autocomplete": "off",
        }),
    )
    pin = forms.CharField(
        label="Password (4-digit PIN)",
        max_length=4,
        min_length=4,
        required=False,
        widget=forms.PasswordInput(attrs={
            "class": "form-control entrix-input",
            "placeholder": "4-digit PIN (optional — for future use)",
            "inputmode": "numeric",
            "maxlength": 4,
            "autocomplete": "new-password",
        }),
    )

    def clean_username(self):
        # `.get(...)` + `or ""` so a missing/None/blank value are all
        # treated the same way instead of raising on `.strip()`.
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            # Optional field left blank — return None (not "") so the
            # instance's username is NULL. This is critical: two blank
            # usernames stored as "" would collide on the unique constraint
            # during ModelForm._post_clean()/validate_unique() and wrongly
            # raise "… with this Username already exists.", whereas SQL
            # treats each NULL as distinct. Only a real, duplicate username
            # should ever trip the uniqueness check.
            return None
        model = self._meta.model
        qs = model.objects.filter(username__iexact=username)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_pin(self):
        pin = (self.cleaned_data.get("pin") or "").strip()
        if not pin:
            # Optional field left blank — this used to still be checked
            # against PIN_REGEX and raise "PIN must be exactly 4 digits.",
            # which silently invalidated the *entire* form (including
            # unrelated changes like a new photo) on every save where the
            # PIN wasn't being reset. That's fixed by returning early here.
            return ""
        if not PIN_REGEX.match(pin):
            raise forms.ValidationError("PIN must be exactly 4 digits.")
        return pin

    def _assert_unique(self, field_name, value, label):
        """
        Case-insensitive uniqueness check against the form's own model,
        excluding the current record on edit (so re-saving an unchanged
        record never trips the check). Shared by Member and Trainer forms.
        """
        model = self._meta.model
        qs = model.objects.filter(**{f"{field_name}__iexact": value})
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"This {label} is already registered.")

    def clean_mobile_number(self):
        mobile = (self.cleaned_data.get("mobile_number") or "").strip()
        if not mobile:
            # Optional at the model level for trainers; only validate when set.
            return mobile
        if not PHONE_REGEX.match(mobile):
            raise forms.ValidationError(
                "Enter a valid mobile number using digits (0-9) and optional leading plus (+) symbol only."
            )
        self._assert_unique("mobile_number", mobile, "mobile number")
        return mobile

    def clean_email(self):
        # Optional field: coerce None/missing to "" first (matches existing
        # behaviour), validate format only when present, then enforce
        # uniqueness across the model excluding the current record on edit.
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            return email
        if "@" not in email or "." not in email.split("@")[-1]:
            raise forms.ValidationError("Enter a valid email address.")
        self._assert_unique("email", email, "email address")
        return email

    def save(self, commit=True):
        instance = super().save(commit=False)
        pin = self.cleaned_data.get("pin")
        username = self.cleaned_data.get("username")

        if pin:
            instance.set_pin(pin)
        elif not instance.pk:
            # New record, no PIN given — leave it unset rather than
            # hashing an empty string into password_pin.
            instance.password_pin = None

        if username:
            instance.username = username
        elif not instance.pk:
            # New record, no username given — leave it unset. (On edit,
            # ModelForm's own construct_instance() already wrote "" onto
            # instance.username; the view restores the original value in
            # that case since blank on edit means "keep existing".)
            instance.username = None

        if commit:
            instance.save()
        return instance


class MemberRegistrationForm(LoginCredentialsMixin):
    """
    Form for Member Registration Wizard in masters app.
    Covers basic, contact, health, membership plan, login and biometric
    (display-only) attributes. The biometric wizard step has been removed —
    `biometric_id` is generated automatically on save (see Member.save()).
    """

    class Meta:
        model = Member
        fields = [
            "full_name",
            "date_of_birth",
            "gender",
            "blood_group",
            "mobile_number",
            "email",
            "join_date",
            "address",
            "height",
            "weight",
            "fitness_goal",
            "medical_condition",
            "membership_plan",
            "amount_paid",
            "photo",
            "username",
            "pin",
        ]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control entrix-input", "placeholder": "Enter the name", "required": True}),
            "date_of_birth": forms.DateInput(attrs={"type": "date", "class": "form-control entrix-input", "id": "dob", "required": True, "max": "9999-12-31"}),
            "gender": forms.Select(attrs={"class": "form-select entrix-input", "required": True}),
            "blood_group": forms.Select(choices=BLOOD_GROUP_CHOICES, attrs={"class": "form-select entrix-input", "id": "memberBloodGroup", "required": True}),
            "mobile_number": forms.TextInput(attrs={
                "class": "form-control entrix-input",
                "placeholder": "Enter mobile number",
                "required": True,
                "inputmode": "numeric",
                "maxlength": 15,
                "pattern": r"^\+?[0-9]+$",
                "oninput": "this.value = this.value.replace(/[^\\+0-9]/g, '').replace(/(?!^)\\+/g, '')",
            }),
            "email": forms.EmailInput(attrs={"class": "form-control entrix-input", "placeholder": "member@example.com"}),
            "join_date": forms.DateInput(attrs={"type": "date", "class": "form-control entrix-input"}),
            "address": forms.Textarea(attrs={"class": "form-control entrix-input", "rows": 2, "placeholder": "Full residential address"}),
            "height": forms.TextInput(attrs={"class": "form-control entrix-input", "placeholder": "Enter height in cm", "autocomplete": "off"}),
            "weight": forms.TextInput(attrs={"class": "form-control entrix-input", "placeholder": "Enter weight in kg", "autocomplete": "off"}),
            "fitness_goal": forms.TextInput(attrs={"class": "form-control entrix-input", "placeholder": "e.g. Weight Loss, Muscle Gain...", "autocomplete": "off"}),
            "medical_condition": forms.Textarea(attrs={"class": "form-control entrix-input", "rows": 3, "placeholder": "e.g. Asthma, previous injuries, allergies...", "autocomplete": "off"}),
            "membership_plan": forms.Select(attrs={"class": "form-select entrix-input", "required": True, "id": "memberMembershipPlan"}),
            "photo": forms.FileInput(attrs={"class": "form-control d-none", "id": "memberPhotoInput", "accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["membership_plan"].queryset = MembershipPlan.objects.filter(is_active=True).order_by("price")
        self.fields["membership_plan"].empty_label = "Select membership plan..."
        # Change 5 — Membership Plan is mandatory for both create and edit.
        self.fields["membership_plan"].required = True
        self.fields["email"].required = False
        self.fields["address"].required = False
        self.fields["medical_condition"].required = False
        self.fields["height"].required = False
        self.fields["weight"].required = False
        self.fields["fitness_goal"].required = False
        # item 2 — these three must always be mandatory in the wizard,
        # regardless of what blank=True/False is set to on the model column.
        self.fields["gender"].required = True
        self.fields["blood_group"].required = True
        self.fields["blood_group"].choices = BLOOD_GROUP_CHOICES
        self.fields["date_of_birth"].required = True
        # Photo is required at registration. The model field itself is
        # Photo is optional for both registration and edits (Change 2B).
        self.fields["photo"].required = False
        # username/pin are optional everywhere (see LoginCredentialsMixin) —
        # nothing further to do here.

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")
        if dob and dob.year > 9999:
            raise forms.ValidationError("Year cannot exceed 4 digits.")
        return dob

    def save(self, commit=True):
        instance = forms.ModelForm.save(self, commit=False)
        pin = self.cleaned_data.get("pin")
        username = self.cleaned_data.get("username")

        if pin:
            instance.set_pin(pin)
        elif not instance.pk:
            instance.password_pin = None

        if username:
            instance.username = username
        elif not instance.pk:
            instance.username = None

        if commit:
            instance.save()
        return instance


class TrainerRegistrationForm(LoginCredentialsMixin):
    """
    Form for Trainer Registration Wizard in masters app.
    Covers basic information, employment terms, schedule, login credentials,
    and a display-only Biometric ID. The biometric wizard step has been
    removed — `biometric_id` is generated automatically on save.
    """

    designation = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "form-select entrix-input", "id": "t_designation"})
    )

    class Meta:
        model = Trainer
        fields = [
            "full_name",
            "date_of_birth",
            "gender",
            "blood_group",
            "mobile_number",
            "email",
            "address",
            "designation",
            "joining_date",
            "salary",
            "working_status",
            "working_time",
            "photo",
            "username",
            "pin",
        ]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control entrix-input", "id": "t_name", "placeholder": "Enter name", "required": True}),
            "date_of_birth": forms.DateInput(attrs={"type": "date", "class": "form-control entrix-input", "id": "t_dob", "required": True, "max": "9999-12-31"}),
            "gender": forms.Select(attrs={"class": "form-select entrix-input", "id": "t_gender", "required": True}),
            "blood_group": forms.Select(choices=BLOOD_GROUP_CHOICES, attrs={"class": "form-select entrix-input", "id": "t_blood_group", "required": True}),
            "mobile_number": forms.TextInput(attrs={
                "class": "form-control entrix-input",
                "id": "t_mobile",
                "placeholder": "Enter mobile number",
                "required": True,
                "inputmode": "numeric",
                "maxlength": 15,
                "pattern": r"^\+?[0-9]+$",
                "oninput": "this.value = this.value.replace(/[^\\+0-9]/g, '').replace(/(?!^)\\+/g, '')",
            }),
            "email": forms.EmailInput(attrs={"class": "form-control entrix-input", "id": "t_email", "placeholder": "trainer@example.com"}),
            "address": forms.TextInput(attrs={"class": "form-control entrix-input", "id": "t_address", "placeholder": "Enter full residential address"}),
            "joining_date": forms.DateInput(attrs={"type": "date", "class": "form-control entrix-input", "id": "t_joining"}),
            "salary": forms.NumberInput(attrs={"class": "form-control entrix-input", "id": "t_salary", "placeholder": "e.g. 25000"}),
            "working_status": forms.Select(attrs={"class": "form-select entrix-input", "id": "t_working"}),
            "working_time": forms.TextInput(attrs={"class": "form-control entrix-input", "id": "t_time", "placeholder": "e.g. 06:00 - 14:00"}),
            "photo": forms.FileInput(attrs={"class": "form-control d-none", "id": "trainerPhotoInputReg", "accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["address"].required = False
        self.fields["salary"].required = False
        self.fields["working_time"].required = False
        self.fields["email"].required = False
        self.fields["gender"].required = True
        self.fields["blood_group"].required = True
        self.fields["blood_group"].choices = BLOOD_GROUP_CHOICES
        self.fields["date_of_birth"].required = True
        self.fields["designation"].choices = [
            (d.name, d.name) for d in TrainerDesignation.objects.filter(is_active=True)
        ]

        # Photo is optional for both registration and edits (Change 2B).
        self.fields["photo"].required = False
        # username/pin are optional everywhere (see LoginCredentialsMixin) —
        # nothing further to do here.

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")
        if dob and dob.year > 9999:
            raise forms.ValidationError("Year cannot exceed 4 digits.")
        return dob