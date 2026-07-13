from django.urls import path
 
from .views import CustomerRegistrationView, MembershipPlanView
 

 
urlpatterns = [
    path("membership-plans/", MembershipPlanView.as_view(), name="membership-plans"),
    path("customer-registration/", CustomerRegistrationView.as_view(), name="customer-registration"),
]