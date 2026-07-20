from django.urls import path

from .views import AttendanceManagementView
from .views_adms import IClockCDataView, IClockGetRequestView, IClockPingView

urlpatterns = [
    path("attendance-management/", AttendanceManagementView.as_view(), name="attendance-management"),
    path("transactions/attendance-management/", AttendanceManagementView.as_view()),

    # -----------------------------------------------------------------
    # eSSL ADMS (iclock PUSH protocol) — biometric device endpoints.
    # Devices are configured to push attendance to this server in real time.
    # -----------------------------------------------------------------
    path("iclock/", IClockPingView.as_view()),
    path("iclock/cdata", IClockCDataView.as_view(), name="adms-cdata"),
    path("iclock/cdata.aspx", IClockCDataView.as_view(), name="adms-cdata-r"),
    path("iclock/getrequest", IClockGetRequestView.as_view(), name="adms-getrequest"),
    path("iclock/ping", IClockPingView.as_view(), name="adms-ping"),
]
