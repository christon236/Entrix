from django import forms
from main_app.models import Attendance, Member


class AttendanceFilterForm(forms.Form):
    """
    Filter form for querying attendance records by date, search query,
    membership status, and attendance status.
    """

    date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control entrix-input",
                "id": "filterDate",
            }
        ),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control border-0 bg-transparent shadow-none p-0 m-0",
                "placeholder": "Search by Member Name, ID or Fingerprint...",
                "id": "filterSearch",
                "style": "flex: 1 1 0% !important; min-width: 0 !important; width: 100% !important; outline: none !important; box-shadow: none !important;",
            }
        ),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("all", "All Status"), ("inside", "Currently Inside"), ("checked_out", "Checked Out")],
        widget=forms.Select(
            attrs={
                "class": "form-select entrix-filter-select",
                "id": "filterStatus",
            }
        ),
    )


class ManualAttendanceForm(forms.ModelForm):
    """
    Bootstrap ModelForm for manually logging check-ins or check-outs
    in the Attendance Management module.
    """

    class Meta:
        model = Attendance
        fields = [
            "member",
            "date",
            "entry_time",
            "exit_time",
            "status",
            "fingerprint_id",
            "notes",
        ]
        widgets = {
            "member": forms.Select(
                attrs={
                    "class": "form-select entrix-input",
                    "id": "manualMember",
                }
            ),
            "date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control entrix-input",
                }
            ),
            "entry_time": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "form-control entrix-input",
                }
            ),
            "exit_time": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "form-control entrix-input",
                }
            ),
            "status": forms.Select(
                attrs={
                    "class": "form-select entrix-input",
                }
            ),
            "fingerprint_id": forms.TextInput(
                attrs={
                    "class": "form-control entrix-input",
                    "placeholder": "e.g. FP-1024",
                }
            ),
            "notes": forms.TextInput(
                attrs={
                    "class": "form-control entrix-input",
                    "placeholder": "Optional manual override reason...",
                }
            ),
        }
        help_texts = {
            "fingerprint_id": "Optional if check-in is logged manually by admin.",
            "status": "Set to Inside upon entry, Checked Out upon exit.",
        }

    def clean(self):
        cleaned_data = super().clean()
        entry_time = cleaned_data.get("entry_time")
        exit_time = cleaned_data.get("exit_time")

        if entry_time and exit_time and exit_time < entry_time:
            self.add_error("exit_time", "Exit time cannot be earlier than entry time.")

        return cleaned_data
