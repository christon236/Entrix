
import re
from django import forms
from main_app.models import Member
from .models import MembershipPlan, Trainer
 
 
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
            "discount_percentage",
            "joining_fee",
            "max_freeze_days",
            "access_type",
            "status",
            "display_order",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control entrix-input",
                    "placeholder": "e.g. Quarterly Fitness Plan",
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
                attrs={"class": "form-control entrix-input", "placeholder": "e.g. 3", "min": 1}
            ),
            "duration_type": forms.Select(attrs={"class": "form-select entrix-input"}),
            "price": forms.NumberInput(
                attrs={"class": "form-control entrix-input", "placeholder": "0.00", "min": 0, "step": "0.01"}
            ),
            "discount_percentage": forms.NumberInput(
                attrs={"class": "form-control entrix-input", "placeholder": "0", "min": 0, "max": 100, "step": "0.01"}
            ),
            "joining_fee": forms.NumberInput(
                attrs={"class": "form-control entrix-input", "placeholder": "0.00", "min": 0, "step": "0.01"}
            ),
            "max_freeze_days": forms.NumberInput(
                attrs={"class": "form-control entrix-input", "placeholder": "e.g. 15", "min": 0}
            ),
            "access_type": forms.Select(attrs={"class": "form-select entrix-input"}),
            "status": forms.Select(attrs={"class": "form-select entrix-input"}),
            "display_order": forms.NumberInput(
                attrs={"class": "form-control entrix-input", "placeholder": "0", "min": 0}
            ),
        }
        help_texts = {
            "discount_percentage": "Applied automatically to the price at checkout.",
            "max_freeze_days": "Number of days a member may pause this plan per cycle.",
            "display_order": "Lower numbers appear first on the registration page.",
        }
 
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
 
    def clean_discount_percentage(self):
        discount = self.cleaned_data["discount_percentage"]
        if discount > 100:
            raise forms.ValidationError("Discount cannot exceed 100%.")
        if discount < 0:
            raise forms.ValidationError("Discount cannot be negative.")
        return discount
 
    def clean_joining_fee(self):
        joining_fee = self.cleaned_data["joining_fee"]
        if joining_fee < 0:
            raise forms.ValidationError("Joining fee cannot be negative.")
        return joining_fee
 
    def clean_display_order(self):
        display_order = self.cleaned_data["display_order"]
        if display_order < 0:
            raise forms.ValidationError("Display order cannot be negative.")
        return display_order


class MemberRegistrationForm(forms.ModelForm):
    """
    Form for Member Registration Wizard in masters app.
    Covers all basic, contact, health, membership plan, and biometric attributes.
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
            "photo",
            "fingerprint_id",
        ]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control entrix-input", "placeholder": "Enter Full Name", "required": True}),
            "date_of_birth": forms.DateInput(attrs={"type": "date", "class": "form-control entrix-input", "id": "dob"}),
            "gender": forms.Select(attrs={"class": "form-select entrix-input"}),
            "blood_group": forms.Select(attrs={"class": "form-select entrix-input"}),
            "mobile_number": forms.TextInput(attrs={"class": "form-control entrix-input", "placeholder": "Enter Mobile Number", "required": True}),
            "email": forms.EmailInput(attrs={"class": "form-control entrix-input", "placeholder": "Enter Email Address"}),
            "join_date": forms.DateInput(attrs={"type": "date", "class": "form-control entrix-input"}),
            "address": forms.Textarea(attrs={"class": "form-control entrix-input", "rows": 2, "placeholder": "Enter Residential Address"}),
            "height": forms.TextInput(attrs={"class": "form-control entrix-input", "placeholder": "Enter Height"}),
            "weight": forms.TextInput(attrs={"class": "form-control entrix-input", "placeholder": "Enter Weight"}),
            "fitness_goal": forms.TextInput(attrs={"class": "form-control entrix-input", "placeholder": "Enter Fitness Goal"}),
            "medical_condition": forms.Textarea(attrs={"class": "form-control entrix-input", "rows": 3, "placeholder": "Enter Medical Conditions (if any)"}),
            "membership_plan": forms.Select(attrs={"class": "form-select entrix-input"}),
            "photo": forms.FileInput(attrs={"class": "form-control d-none", "id": "memberPhotoInput", "accept": "image/*"}),
            "fingerprint_id": forms.TextInput(attrs={"class": "form-control entrix-input", "readonly": True, "placeholder": "Capture fingerprint..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["membership_plan"].queryset = MembershipPlan.objects.filter(is_active=True).order_by("price")
        self.fields["membership_plan"].empty_label = "Select membership plan..."
        self.fields["email"].required = False
        self.fields["address"].required = False
        self.fields["fingerprint_id"].required = False
        self.fields["medical_condition"].required = False
        self.fields["height"].required = False
        self.fields["weight"].required = False
        self.fields["fitness_goal"].required = False

    def clean_mobile_number(self):
        val = self.cleaned_data.get("mobile_number", "")
        if val and not re.match(r"^\+?[0-9]+$", val):
            raise forms.ValidationError("Only numbers (0-9) and optional leading plus (+) are allowed.")
        return val


class TrainerRegistrationForm(forms.ModelForm):
    """
    Form for Trainer Registration Wizard in masters app.
    Covers basic information, employment terms, schedule, and biometric access.
    """

    class Meta:
        model = Trainer
        fields = [
            "full_name",
            "gender",
            "mobile_number",
            "address",
            "designation",
            "joining_date",
            "salary",
            "working_status",
            "working_time",
            "photo",
            "fingerprint_id",
        ]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control entrix-input", "id": "t_name", "placeholder": "Enter Trainer Name", "required": True}),
            "gender": forms.Select(attrs={"class": "form-select entrix-input", "id": "t_gender"}),
            "mobile_number": forms.TextInput(attrs={"class": "form-control entrix-input", "id": "t_mobile", "placeholder": "Enter Mobile Number", "required": True}),
            "address": forms.TextInput(attrs={"class": "form-control entrix-input", "id": "t_address", "placeholder": "Enter Residential Address"}),
            "designation": forms.Select(attrs={"class": "form-select entrix-input", "id": "t_designation"}),
            "joining_date": forms.DateInput(attrs={"type": "date", "class": "form-control entrix-input", "id": "t_joining"}),
            "salary": forms.NumberInput(attrs={"class": "form-control entrix-input", "id": "t_salary", "placeholder": "Enter Salary"}),
            "working_status": forms.Select(attrs={"class": "form-select entrix-input", "id": "t_working"}),
            "working_time": forms.TextInput(attrs={"class": "form-control entrix-input", "id": "t_time", "placeholder": "Enter Working Time"}),
            "photo": forms.FileInput(attrs={"class": "form-control d-none", "id": "trainerPhotoInputReg", "accept": "image/*"}),
            "fingerprint_id": forms.TextInput(attrs={"class": "form-control entrix-input", "readonly": True, "placeholder": "Capture fingerprint..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["address"].required = False
        self.fields["salary"].required = False
        self.fields["working_time"].required = False
        self.fields["fingerprint_id"].required = False

    def clean_mobile_number(self):
        val = self.cleaned_data.get("mobile_number", "")
        if val and not re.match(r"^\+?[0-9]+$", val):
            raise forms.ValidationError("Only numbers (0-9) and optional leading plus (+) are allowed.")
        return val

 