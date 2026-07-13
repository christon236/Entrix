from django import forms
from masters.models import MembershipPlan


class AttendanceReportFilterForm(forms.Form):
    """
    Filter form for the ENTRIX Attendance Report Module.
    Supports preset date ranges, custom start/end dates,
    member search by ID/Name, and membership plan filter.
    """

    DATE_PRESETS = [
        ("today", "Today"),
        ("yesterday", "Yesterday"),
        ("last_7_days", "Last 7 Days"),
        ("this_month", "This Month"),
        ("last_month", "Last Month"),
        ("custom", "Custom Date Range"),
    ]

    date_preset = forms.ChoiceField(
        choices=DATE_PRESETS,
        required=False,
        initial="this_month",
        widget=forms.Select(
            attrs={
                "class": "form-select entrix-input fw-semibold",
                "id": "id_date_preset",
            }
        ),
    )

    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control entrix-input",
                "id": "id_start_date",
            }
        ),
    )

    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control entrix-input",
                "id": "id_end_date",
            }
        ),
    )

    member_search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control entrix-input",
                "placeholder": "Search by Member ID, Name, or Mobile...",
                "id": "id_member_search",
            }
        ),
    )

    membership_plan = forms.ModelChoiceField(
        queryset=MembershipPlan.objects.none(),
        required=False,
        empty_label="All Membership Plans",
        widget=forms.Select(
            attrs={
                "class": "form-select entrix-input",
                "id": "id_membership_plan",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["membership_plan"].queryset = MembershipPlan.objects.filter(is_active=True).order_by("price")
