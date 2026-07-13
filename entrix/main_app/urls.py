from django.urls import path
from .views import LandingView, DashboardView, EntrixLoginView, EntrixLogoutView, ProfileView, ForgotPasswordView

urlpatterns = [
    path("", LandingView.as_view(), name="landing"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("login/", EntrixLoginView.as_view(), name="login"),
    path("logout/", EntrixLogoutView.as_view(), name="logout"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
]