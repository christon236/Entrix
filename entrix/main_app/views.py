
import random
import re
import time
from datetime import timedelta
 
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
 
from masters.models import Trainer
from .forms import (
    EntrixLoginForm,
    GymProfileForm,
    AdminProfileForm,
    AdminUserForm,
    EntrixPasswordChangeForm,
)
from .models import Attendance, Member, MembershipPlan, GymProfile, AdminProfile
 
# =========================================================
# LANDING & AUTHENTICATION VIEWS
# =========================================================

class LandingView(View):
    """
    Landing Page before Login page.
    Redirects to dashboard directly if user is already logged in.
    """
    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return render(request, "main_app/landing.html")
 
 
class EntrixLoginView(LoginView):
    """
    Class Based View for ENTRIX authentication.
    Renders the branded login page and handles the 4-digit captcha
    verification flow on top of Django's built-in LoginView.
    """
 
    template_name = "main_app/login.html"
    authentication_form = EntrixLoginForm
    redirect_authenticated_user = True
 
    def get(self, request, *args, **kwargs):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("action") == "refresh_captcha":
            new_captcha = str(random.randint(1000, 9999))
            request.session["login_captcha"] = new_captcha
            return JsonResponse({"captcha": new_captcha})
        return super().get(request, *args, **kwargs)
 
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not self.request.session.get("login_captcha") or self.request.GET.get("refresh") == "1":
            self.request.session["login_captcha"] = str(random.randint(1000, 9999))
        context["captcha_digits"] = self.request.session.get("login_captcha", "")
        return context
 
    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session.set_expiry(0)
        messages.success(
            self.request,
            f"Welcome back, {self.request.user.get_username()}!",
        )
        return response
 
    def form_invalid(self, form):
        self.request.session["login_captcha"] = str(random.randint(1000, 9999))
        messages.error(self.request, "Login failed. Please check your username, password, and verification code.")
        return super().form_invalid(form)
 
    def get_success_url(self):
        return reverse_lazy("dashboard")
 
 
class EntrixLogoutView(View):
    """
    Class Based View that logs the user out and redirects
    to the login page with a confirmation message.
    """
 
    def get(self, request, *args, **kwargs):
        return self._perform_logout(request)
 
    def post(self, request, *args, **kwargs):
        return self._perform_logout(request)
 
    def _perform_logout(self, request):
        logout(request)
        messages.info(request, "You have been logged out successfully.")
        return redirect("login")
 
 
# =========================================================
# DASHBOARD VIEW (new — Module 2)
# =========================================================
 
# Placeholder until a settings/config module exists to manage this per-branch.
GYM_MAX_CAPACITY = 100
 
 
class DashboardView(LoginRequiredMixin, TemplateView):
    """
    Main ENTRIX dashboard. Aggregates member, attendance and membership
    statistics into a single context using efficient ORM queries
    (aggregates/annotations instead of looping in Python).
    """
 
    template_name = "main_app/dashboard.html"
    login_url = "login"
 
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
 
        today = timezone.localdate()
        week_from_now = today + timedelta(days=7)
        seven_days_ago = today - timedelta(days=6)  # inclusive 7-day window
 
        # ---- Greeting ----
        hour = timezone.localtime().hour
        if hour < 12:
            greeting = "Good Morning"
        elif hour < 17:
            greeting = "Good Afternoon"
        else:
            greeting = "Good Evening"
 
        # ---- Core counts ----
        total_members = Member.objects.count()
        active_memberships = Member.objects.filter(
            is_active=True, membership_end_date__gte=today
        ).count()
        expired_memberships = Member.objects.filter(
            membership_end_date__lt=today
        ).count()
        plans_available = MembershipPlan.objects.filter(
            status=MembershipPlan.STATUS_ACTIVE
        ).count()
 
        # ---- Attendance / occupancy ----
        today_attendance_qs = Attendance.objects.filter(date=today)
        today_checkins = today_attendance_qs.count()
        today_checkouts = today_attendance_qs.filter(exit_time__isnull=False).count()
        currently_inside = today_attendance_qs.filter(
            status=Attendance.STATUS_INSIDE
        ).count()
 
        gym_profile = GymProfile.get_instance()
        gym_max_capacity = gym_profile.max_occupancy if (gym_profile.max_occupancy and gym_profile.max_occupancy > 0) else 100
        occupancy_percentage = 0
        if gym_max_capacity > 0:
            occupancy_percentage = round((currently_inside / gym_max_capacity) * 100, 1)
 
        avg_daily_attendance = (
            Attendance.objects.filter(date__gte=seven_days_ago).count() / 7
        )
 
        # ---- Revenue / renewals ----
        today_new_members = Member.objects.filter(join_date=today)
        today_new_members_count = today_new_members.count()
        today_revenue = (
            today_new_members.aggregate(total=Sum("membership_plan__price"))["total"]
            or 0
        )
 
        upcoming_renewals = (
            Member.objects.select_related("membership_plan")
            .filter(membership_end_date__range=[today, week_from_now])
            .order_by("membership_end_date")
        )
        pending_renewals_count = upcoming_renewals.count()
 
        # ---- Tables ----
        recent_attendance = (
            Attendance.objects.select_related("member", "member__membership_plan")
            .order_by("-date", "-entry_time")[:8]
        )
 
        membership_expiry = (
            Member.objects.select_related("membership_plan")
            .filter(membership_end_date__gte=today)
            .order_by("membership_end_date")[:8]
        )
 
        # ---- Live activity feed (merged from recent attendance + new members) ----
        activity_feed = []
 
        for record in Attendance.objects.select_related("member").order_by("-date", "-entry_time")[:5]:
            if record.status == Attendance.STATUS_INSIDE:
                text = f"{record.member.full_name} entered the gym"
                icon, color = "bi-box-arrow-in-right", "success"
            elif record.status == Attendance.STATUS_CHECKED_OUT:
                text = f"{record.member.full_name} checked out"
                icon, color = "bi-box-arrow-right", "secondary"
            else:
                text = f"{record.member.full_name}'s access was denied (expired)"
                icon, color = "bi-x-circle", "danger"
            activity_feed.append({"text": text, "icon": icon, "color": color, "time": record.created_at})
 
        for member in Member.objects.order_by("-created_at")[:5]:
            activity_feed.append(
                {
                    "text": f"New member registered: {member.full_name}",
                    "icon": "bi-person-plus",
                    "color": "primary",
                    "time": member.created_at,
                }
            )
 
        activity_feed.sort(key=lambda item: item["time"], reverse=True)
        activity_feed = activity_feed[:6]
 
        context.update(
            {
                "greeting": greeting,
                "today": today,
                # Stat cards
                "total_members": total_members,
                "currently_inside": currently_inside,
                "today_checkins": today_checkins,
                "today_checkouts": today_checkouts,
                "active_memberships": active_memberships,
                "expired_memberships": expired_memberships,
                "plans_available": plans_available,
                "occupancy_percentage": occupancy_percentage,
                # Quick status row
                "upcoming_renewals_count": upcoming_renewals.count(),
                "today_new_members_count": today_new_members_count,
                "today_revenue": today_revenue,
                "pending_renewals_count": pending_renewals_count,
                "gym_max_capacity": gym_max_capacity,
                "avg_daily_attendance": round(avg_daily_attendance, 1),
                # Tables / feeds
                "recent_attendance": recent_attendance,
                "membership_expiry": membership_expiry,
                "activity_feed": activity_feed,
            }
        )
        return context


# =========================================================
# PROFILE VIEW (Module: Admin & Gym Profile)
# =========================================================

class ProfileView(LoginRequiredMixin, View):
    """
    Consolidated Class Based View for Admin Profile, Gym Details, Trainers, and Account Management.
    Handles Display, Edit, Update, Image Uploads, and Password Changes in ONE single page and view.
    """
    template_name = "main_app/profile.html"
    login_url = "login"

    def get(self, request, *args, **kwargs):
        # AJAX Endpoint to fetch trainer details for the modal
        if request.GET.get("action") == "get_trainer":
            trainer_id = request.GET.get("id")
            trainer = get_object_or_404(Trainer, pk=trainer_id)
            joining_year = trainer.joining_date.year if trainer.joining_date else timezone.localdate().year
            exp_years = max(1, timezone.localdate().year - joining_year)
            return JsonResponse({
                "id": trainer.pk,
                "trainer_id": trainer.trainer_id,
                "name": trainer.full_name,
                "gender": trainer.gender,
                "mobile": trainer.mobile_number,
                "address": trainer.address,
                "designation": trainer.designation,
                "joining": trainer.joining_date.strftime("%d %b %Y") if trainer.joining_date else "",
                "salary": f"₹{trainer.salary:,.0f}" if trainer.salary else "₹0",
                "salary_raw": str(trainer.salary or ""),
                "working": trainer.working_status,
                "time": trainer.working_time,
                "photo": trainer.photo.url if (trainer.photo and trainer.photo.name) else "",
                "present": "Yes",
                "last": "—",
                "totaldays": "0",
                "username": f"@{trainer.full_name.lower().replace(' ', '.')}",
                "email": f"{trainer.full_name.lower().replace(' ', '.')}@entrixfitness.com" if trainer.full_name else "",
                "assigned_role": trainer.designation,
                "experience": f"{exp_years}+ Years",
                "specialization": trainer.designation,
            })

        today = timezone.localdate()
        total_members = Member.objects.count()
        active_memberships = Member.objects.filter(
            is_active=True, membership_end_date__gte=today
        ).count()
        total_trainers = Trainer.objects.count()
        today_attendance_count = Attendance.objects.filter(date=today, status=Attendance.STATUS_INSIDE).count()
        total_checkins = Attendance.objects.filter(date=today).count()

        gym_profile = GymProfile.get_instance()
        admin_profile, _ = AdminProfile.objects.get_or_create(user=request.user)
        trainers_qs = Trainer.objects.all()
        page_number = request.GET.get("page", 1)
        trainers_page = Paginator(trainers_qs, 10).get_page(page_number)

        gym_form = GymProfileForm(instance=gym_profile)
        admin_user_form = AdminUserForm(instance=request.user)
        admin_profile_form = AdminProfileForm(instance=admin_profile)
        password_form = EntrixPasswordChangeForm(user=request.user)

        total_membership_plans = MembershipPlan.objects.count()

        context = {
            "total_members": total_members,
            "active_memberships": active_memberships,
            "total_trainers": total_trainers,
            "total_membership_plans": total_membership_plans,
            "active_members": active_memberships,
            "today_attendance_display": f"{today_attendance_count} / {total_trainers}",
            "currently_inside": today_attendance_count,
            "gym_profile": gym_profile,
            "admin_profile": admin_profile,
            "trainers": trainers_page,
            "gym_form": gym_form,
            "admin_user_form": admin_user_form,
            "admin_profile_form": admin_profile_form,
            "password_form": password_form,
        }
        return TemplateView.as_view(template_name=self.template_name, extra_context=context)(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")

        if action == "toggle_trainer_status":
            trainer_pk = request.POST.get("trainer_pk")
            trainer = get_object_or_404(Trainer, pk=trainer_pk)
            if trainer.working_status == Trainer.STATUS_WORKING:
                trainer.working_status = Trainer.STATUS_LEFT
            else:
                trainer.working_status = Trainer.STATUS_WORKING
            trainer.save()
            return JsonResponse({
                "status": "success",
                "new_status": trainer.working_status,
                "label": "ACTIVE" if trainer.working_status == Trainer.STATUS_WORKING else "INACTIVE"
            })

        if action == "update_gym":
            gym_profile = GymProfile.get_instance()
            form = GymProfileForm(request.POST, request.FILES, instance=gym_profile)
            if form.is_valid():
                saved_gym = form.save()
                global GYM_MAX_CAPACITY
                GYM_MAX_CAPACITY = saved_gym.max_occupancy or 100
                messages.success(request, "Gym details and working schedule updated successfully.")
            else:
                messages.error(request, "Error updating gym details. Please check form fields.")

        elif action == "update_trainer":
            trainer_pk = request.POST.get("trainer_pk")
            trainer = get_object_or_404(Trainer, pk=trainer_pk)
            new_mobile = request.POST.get("t_mobile", "").strip()
            if new_mobile and not re.match(r"^\+?[0-9]+$", new_mobile):
                messages.error(request, "Invalid mobile number. Only numbers (0-9) and optional leading plus (+) are allowed.")
                return redirect("profile")
            if new_mobile:
                trainer.mobile_number = new_mobile
            trainer.full_name = request.POST.get("t_name", trainer.full_name)
            trainer.gender = request.POST.get("t_gender", trainer.gender)
            trainer.address = request.POST.get("t_address", trainer.address)
            trainer.designation = request.POST.get("t_designation", trainer.designation)
            trainer.working_status = request.POST.get("t_working", trainer.working_status)
            trainer.working_time = request.POST.get("t_time", trainer.working_time)
            
            salary_val = request.POST.get("t_salary", "").replace("₹", "").replace(",", "").strip()
            if salary_val:
                try:
                    trainer.salary = float(salary_val)
                except ValueError:
                    pass

            if "trainer_photo" in request.FILES:
                trainer.photo = request.FILES["trainer_photo"]

            trainer.save()
            messages.success(request, f"Trainer {trainer.full_name} updated successfully.")

        elif action == "update_admin_profile":
            u_form = AdminUserForm(request.POST, instance=request.user)
            admin_profile, _ = AdminProfile.objects.get_or_create(user=request.user)
            p_form = AdminProfileForm(request.POST, request.FILES, instance=admin_profile)

            if u_form.is_valid() and p_form.is_valid():
                u_form.save()
                p_form.save()
                messages.success(request, "Admin profile and contact details updated successfully.")
            else:
                messages.error(request, "Failed to update admin profile. Check values.")

        elif action == "change_password":
            password_form = EntrixPasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Your password has been changed successfully.")
            else:
                for error in password_form.errors.values():
                    messages.error(request, f"Password Error: {error[0]}")

        return redirect("profile")


class ForgotPasswordView(View):
    """
    Production-ready Forgot Password View with 3-step verification:
    Step 1: Email verification & OTP dispatch (6-digit, 5-min expiry, 60s resend timer)
    Step 2: OTP + 4-digit Captcha validation with Refresh option
    Step 3: New Password & Confirm Password (min 4 characters)
    """
    template_name = "main_app/forgot_password.html"

    def get(self, request, *args, **kwargs):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("action") == "refresh_captcha":
            new_captcha = str(random.randint(1000, 9999))
            request.session["forgot_captcha"] = new_captcha
            return JsonResponse({"captcha": new_captcha})
            
        if request.GET.get("action") == "change_username":
            request.session.pop("reset_step", None)
            request.session.pop("reset_otp", None)
            request.session.pop("reset_email", None)
            request.session.pop("reset_username", None)
            request.session.pop("reset_otp_verified", None)
            return redirect("forgot-password")

        step = request.session.get("reset_step", 1)
        if not request.session.get("forgot_captcha") or request.GET.get("refresh") == "1":
            request.session["forgot_captcha"] = str(random.randint(1000, 9999))
            
        context = {
            "step": step,
            "captcha_digits": request.session.get("forgot_captcha", ""),
            "reset_email": request.session.get("reset_email", ""),
            "reset_username": request.session.get("reset_username", ""),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")

        if action == "refresh_captcha":
            new_captcha = str(random.randint(1000, 9999))
            request.session["forgot_captcha"] = new_captcha
            return JsonResponse({"captcha": new_captcha})

        elif action == "change_username":
            request.session.pop("reset_step", None)
            request.session.pop("reset_otp", None)
            request.session.pop("reset_email", None)
            request.session.pop("reset_username", None)
            request.session.pop("reset_otp_verified", None)
            return redirect("forgot-password")

        elif action == "send_otp":
            username = request.POST.get("username", "").strip()
            if not username:
                messages.error(request, "Please enter your username.")
                return render(request, self.template_name, {
                    "step": 1,
                    "username_error": "Please enter your username.",
                    "username_input": username
                })

            now = time.time()
            next_send = request.session.get("reset_otp_next_send", 0)
            if now < next_send:
                remaining = int(next_send - now)
                messages.error(request, f"Please wait {remaining} seconds before requesting another OTP.")
                return redirect("forgot-password")

            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.filter(username__iexact=username).first()
            if not user:
                error_msg = "Username does not exist. Please check your username and try again."
                messages.error(request, error_msg)
                return render(request, self.template_name, {
                    "step": 1,
                    "username_error": error_msg,
                    "username_input": username
                })

            email = user.email.strip() if user.email else ""
            if not email:
                error_msg = f"No registered email address found for account '{username}'. Please contact your System Administrator."
                messages.error(request, error_msg)
                return render(request, self.template_name, {
                    "step": 1,
                    "username_error": error_msg,
                    "username_input": username
                })

            otp = str(random.randint(100000, 999999))
            captcha = str(random.randint(1000, 9999))
            request.session["reset_username"] = username
            request.session["reset_otp"] = otp
            request.session["reset_email"] = email
            request.session["forgot_captcha"] = captcha
            request.session["reset_otp_expiry"] = now + 300  # 5 minutes
            request.session["reset_otp_next_send"] = now + 60   # 60 seconds resend timer
            request.session["reset_step"] = 2
            request.session["reset_otp_verified"] = False

            # Send MNC-grade Branded HTML Email
            from django.core.mail import send_mail
            subject = "ENTRIX Security Protocol - Password Reset OTP"
            html_message = f"""
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"></head>
            <body style="font-family: 'Inter', Arial, sans-serif; background-color: #0f3357; padding: 40px 10px; margin: 0;">
                <div style="max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.3);">
                    <div style="background: linear-gradient(135deg, #0f3357 0%, #1a4a7e 100%); padding: 30px; text-align: center; border-bottom: 4px solid #f7941d;">
                        <h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 800; letter-spacing: -1px;">ENTRIX</h1>
                        <p style="color: rgba(255,255,255,0.7); margin: 5px 0 0; font-size: 13px; letter-spacing: 0.5px;">ENTERPRISE GYM MANAGEMENT SYSTEM</p>
                    </div>
                    <div style="padding: 35px 30px; color: #2d3748;">
                        <h2 style="font-size: 20px; font-weight: 700; color: #0f3357; margin-top: 0;">Password Reset Authorization</h2>
                        <p style="font-size: 14px; line-height: 1.6; color: #4a5568;">We received a request to reset the security credentials associated with your ENTRIX account (Username: <strong>{username}</strong>, Email: <strong>{email}</strong>). Please use the One-Time Verification Code below to authorize this request:</p>
                        <div style="background: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 12px; padding: 24px; text-align: center; margin: 25px 0;">
                            <span style="font-size: 36px; font-weight: 800; letter-spacing: 8px; color: #f7941d;">{otp}</span>
                        </div>
                        <div style="background: #fffaf0; border-left: 4px solid #f7941d; padding: 12px 16px; border-radius: 4px; margin-bottom: 25px;">
                            <p style="margin: 0; font-size: 13px; color: #9a6700;"><strong>Security Expiration Notice:</strong> This OTP code is single-use and will automatically expire in exactly <strong>5 minutes</strong>.</p>
                        </div>
                        <p style="font-size: 13px; line-height: 1.5; color: #718096; margin-bottom: 0;">If you did not initiate this password reset request, please disregard this email or contact your System Administrator immediately. Your credentials remain secure.</p>
                    </div>
                    <div style="background: #f1f5f9; padding: 18px 30px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0;">
                        <p style="margin: 0;">&copy; ENTRIX Enterprise Security Protocols. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """
            plain_message = f"ENTRIX Security OTP: {otp}. Valid for 5 minutes. If you did not request this, please ignore."
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[ENTRIX EMAIL DEBUG] Generating OTP for {username} ({email}). Code: {otp}")
            print(f"[ENTRIX EMAIL DEBUG - OTP CODE for {username} ({email})]: {otp}")
            try:
                sent_count = send_mail(
                    subject=subject,
                    message=plain_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    html_message=html_message,
                    fail_silently=False
                )
                if sent_count > 0:
                    logger.info(f"[ENTRIX EMAIL SUCCESS] OTP successfully delivered via SMTP to {email} for username {username}.")
                    messages.success(request, f"A 6-digit verification code has been sent to {email}. Valid for 5 minutes.")
                    return redirect("forgot-password")
                else:
                    raise Exception("Mail server returned 0 messages sent without explicit exception.")
            except Exception as e:
                logger.error(f"[ENTRIX EMAIL ERROR] Failed to deliver OTP email to {email}: {str(e)}", exc_info=True)
                print(f"[ENTRIX EMAIL ERROR] Failed to send OTP email to {email}: {str(e)}")
                request.session["reset_step"] = 1
                if not settings.EMAIL_HOST_PASSWORD or "535" in str(e) or "Authentication" in str(e) or "Username and Password not accepted" in str(e):
                    error_msg = f"Email delivery failed: SMTP authentication error for '{settings.EMAIL_HOST_USER}'. Please configure a valid App Password (EMAIL_HOST_PASSWORD) in your environment settings. ({str(e)})"
                else:
                    error_msg = f"Email delivery failed: Unable to send verification code to {email}. Please verify your SMTP server and network configuration. ({str(e)})"
                messages.error(request, error_msg)
                return render(request, self.template_name, {
                    "step": 1,
                    "email_error": error_msg,
                    "username_input": username
                })

        elif action == "verify_otp":
            captcha_input = request.POST.get("captcha", "").strip()
            session_captcha = request.session.get("forgot_captcha", "")
            if captcha_input != session_captcha:
                error_msg = "Invalid 4-digit captcha verification code. Please enter the exact digits displayed."
                messages.error(request, error_msg)
                return render(request, self.template_name, {
                    "step": 2,
                    "captcha_error": error_msg,
                    "captcha_digits": session_captcha,
                    "reset_email": request.session.get("reset_email", ""),
                })

            now = time.time()
            expiry = request.session.get("reset_otp_expiry", 0)
            if now > expiry:
                messages.error(request, "Your OTP has expired after 5 minutes. Please request a new code.")
                request.session["reset_step"] = 1
                return redirect("forgot-password")

            otp_input = request.POST.get("otp", "").strip()
            session_otp = request.session.get("reset_otp", "")
            if not otp_input or otp_input != session_otp:
                error_msg = "Invalid 6-digit verification OTP. Please try again."
                messages.error(request, error_msg)
                return render(request, self.template_name, {
                    "step": 2,
                    "otp_error": error_msg,
                    "captcha_digits": session_captcha,
                    "reset_email": request.session.get("reset_email", ""),
                })

            request.session["reset_step"] = 3
            request.session["reset_otp_verified"] = True
            messages.success(request, "Identity verified successfully. Please enter your new password.")
            return redirect("forgot-password")

        elif action == "reset_password":
            if not request.session.get("reset_otp_verified"):
                messages.error(request, "Unauthorized password reset attempt. Please complete OTP verification.")
                request.session["reset_step"] = 1
                return redirect("forgot-password")

            p1 = request.POST.get("new_password1", "")
            p2 = request.POST.get("new_password2", "")

            if len(p1) < 4:
                error_msg = "Password must be at least 4 characters long."
                messages.error(request, error_msg)
                return render(request, self.template_name, {
                    "step": 3,
                    "password_error": error_msg,
                })

            if p1 != p2:
                error_msg = "New passwords do not match. Please re-enter carefully."
                messages.error(request, error_msg)
                return render(request, self.template_name, {
                    "step": 3,
                    "password_error": error_msg,
                })

            from django.contrib.auth import get_user_model
            User = get_user_model()
            username = request.session.get("reset_username", "").strip()
            user = User.objects.filter(username__iexact=username).first() if username else None
            if not user:
                email = request.session.get("reset_email", "").strip()
                user = User.objects.filter(email__iexact=email).first()
            if not user:
                user = User.objects.filter(username__iexact=request.session.get("reset_email", "").strip()).first()
            if not user:
                user = User.objects.filter(is_superuser=True).first()

            if user:
                user.set_password(p1)
                user.save()
                # Invalidate OTP after use
                request.session.pop("reset_otp", None)
                request.session.pop("reset_otp_verified", None)
                request.session.pop("reset_step", None)
                request.session.pop("reset_username", None)
                request.session.pop("reset_email", None)
                request.session.pop("forgot_captcha", None)
                messages.success(request, "Your password has been successfully reset! Please sign in with your new password.")
                return redirect("login")
            else:
                messages.error(request, "Unable to locate user account. Please contact technical support.")
                return redirect("forgot-password")

        return redirect("forgot-password")


 