
import re
from django import forms
from django.contrib.auth.forms import AuthenticationForm
 
 
class EntrixLoginForm(AuthenticationForm):
    """
    Custom login form for ENTRIX.
    Extends Django's built-in AuthenticationForm to apply Bootstrap 5
    styling and add a 'Remember Me' checkbox.
    """
 
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg entrix-input",
                "placeholder": "Username",
                "autofocus": True,
                "autocomplete": "username",
            }
        )
    )
 
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control form-control-lg entrix-input",
                "placeholder": "Password",
                "autocomplete": "current-password",
            }
        )
    )
 
    captcha = forms.CharField(
        max_length=4,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg entrix-input text-center fw-bold letter-spacing-lg",
                "placeholder": "Enter 4 Digits Captcha",
                "maxlength": "4",
                "pattern": "[0-9]{4}",
                "inputmode": "numeric",
                "autocomplete": "off",
            }
        ),
        error_messages={"required": "Please enter the 4-digit verification code."},
    )

    error_messages = {
        "invalid_login": (
            "Invalid username or password. Please check your credentials "
            "and try again."
        ),
        "inactive": "This account is inactive. Please contact your administrator.",
    }

    def clean_captcha(self):
        captcha_input = self.cleaned_data.get("captcha")
        if self.request and hasattr(self.request, "session"):
            session_captcha = self.request.session.get("login_captcha")
            if not session_captcha or str(captcha_input).strip() != str(session_captcha).strip():
                raise forms.ValidationError("Invalid verification code. Please enter the correct 4 digits.")
        return captcha_input


from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm as BasePasswordChangeForm
from .models import GymProfile, AdminProfile

User = get_user_model()


class GymProfileForm(forms.ModelForm):
    """
    Bootstrap-ready ModelForm for updating Gym Details and Working Schedule.
    """
    class Meta:
        model = GymProfile
        fields = [
            "name", "logo", "address", "contact_number",
            "alternate_contact", "email", "max_occupancy", "schedule_json"
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Gym Name"}),
            "logo": forms.FileInput(attrs={"class": "form-control d-none", "id": "gymLogoInputModal", "accept": "image/*", "onchange": "previewPhoto(this, 'gymLogoPreviewModal')"}),
            "address": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Full Address"}),
            "contact_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Contact Number", "pattern": r"^\+?[0-9]+$", "oninput": "this.value = this.value.replace(/[^\\+0-9]/g, '').replace(/(?!^)\\+/g, '')"}),
            "alternate_contact": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Alternate Contact Number", "pattern": r"^\+?[0-9]+$", "oninput": "this.value = this.value.replace(/[^\\+0-9]/g, '').replace(/(?!^)\\+/g, '')"}),
            "email": forms.EmailField.widget(attrs={"class": "form-control", "placeholder": "Enter Email Address"}),
            "max_occupancy": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "schedule_json": forms.HiddenInput(attrs={"id": "schedule_json_input"}),
        }

    def clean_contact_number(self):
        val = self.cleaned_data.get("contact_number", "")
        if val and not re.match(r"^\+?[0-9]+$", val):
            raise forms.ValidationError("Only numbers (0-9) and optional leading plus (+) are allowed.")
        return val

    def clean_alternate_contact(self):
        val = self.cleaned_data.get("alternate_contact", "")
        if val and not re.match(r"^\+?[0-9]+$", val):
            raise forms.ValidationError("Only numbers (0-9) and optional leading plus (+) are allowed.")
        return val


class AdminUserForm(forms.ModelForm):
    """
    Form for updating admin user basic info (Username, Email).
    """
    class Meta:
        model = User
        fields = ["username", "email"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Username"}),
            "email": forms.EmailField.widget(attrs={"class": "form-control", "placeholder": "Enter Email Address"}),
        }


class AdminProfileForm(forms.ModelForm):
    """
    Form for updating admin extended profile info (Photo, Mobile, Designation).
    """
    class Meta:
        model = AdminProfile
        fields = ["photo", "mobile_number", "designation"]
        widgets = {
            "photo": forms.FileInput(attrs={"class": "form-control d-none", "id": "adminPhotoInputModal", "accept": "image/*"}),
            "mobile_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Mobile Number", "pattern": r"^\+?[0-9]+$", "oninput": "this.value = this.value.replace(/[^\\+0-9]/g, '').replace(/(?!^)\\+/g, '')"}),
            "designation": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Designation"}),
        }

    def clean_mobile_number(self):
        val = self.cleaned_data.get("mobile_number", "")
        if val and not re.match(r"^\+?[0-9]+$", val):
            raise forms.ValidationError("Only numbers (0-9) and optional leading plus (+) are allowed.")
        return val


class EntrixPasswordChangeForm(BasePasswordChangeForm):
    """
    Bootstrap-styled Password Change Form enforcing 4 character minimum length.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control"})
        if "old_password" in self.fields:
            self.fields["old_password"].widget.attrs.update({"placeholder": "Enter Current Password"})
        if "new_password1" in self.fields:
            self.fields["new_password1"].widget.attrs.update({"placeholder": "Enter New Password (min. 4 characters)", "minlength": "4"})
        if "new_password2" in self.fields:
            self.fields["new_password2"].widget.attrs.update({"placeholder": "Confirm New Password", "minlength": "4"})

    def clean_new_password1(self):
        pw = self.cleaned_data.get("new_password1")
        if pw and len(pw) < 4:
            raise forms.ValidationError("Password must be at least 4 characters long.")
        return pw

 