from django.urls import path
from . import views

urlpatterns = [
    path("attendance-report/", views.AttendanceReportView.as_view(), name="attendance-report"),
]