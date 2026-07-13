from django.urls import path
from .views import AttendanceManagementView

urlpatterns = [
    path("attendance-management/", AttendanceManagementView.as_view(), name="attendance-management"),
    path("transactions/attendance-management/", AttendanceManagementView.as_view()),
]
