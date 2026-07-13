
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from main_app.models import Member
from .forms import MemberRegistrationForm, MembershipPlanForm, TrainerRegistrationForm
from .models import MembershipPlan, Trainer
 
 
class MembershipPlanView(LoginRequiredMixin, View):
    """
    Single Class Based View handling the entire Membership Plans module:
    listing, search, filtering, statistics, create, update and delete —
    all served from one URL and one template, using Bootstrap modals
    instead of separate pages.
    """
 
    template_name = "masters/membership-plans.html"
    login_url = "login"
 
    # ---------------------------------------------------------------
    # GET — display page, stats, filtered/searched plan list
    # ---------------------------------------------------------------
 
    def get(self, request, *args, **kwargs):
        context = self._build_context(request)
        return render(request, self.template_name, context)
 
    # ---------------------------------------------------------------
    # POST — create / update / delete, dispatched by hidden 'action' field
    # ---------------------------------------------------------------
 
    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
 
        if action == "create":
            return self._handle_create(request)
        elif action == "update":
            return self._handle_update(request)
        elif action == "delete":
            return self._handle_delete(request)
 
        messages.error(request, "Unknown action.")
        return redirect("membership-plans")
 
    # ---------------------------------------------------------------
    # Action handlers
    # ---------------------------------------------------------------
 
    def _handle_create(self, request):
        form = MembershipPlanForm(request.POST)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.created_by = request.user
            plan.save()
            messages.success(request, f"Plan '{plan.name}' created successfully.")
            return redirect("membership-plans")
 
        messages.error(request, "Please correct the errors below and try again.")
        context = self._build_context(request, add_form=form, open_modal="add")
        return render(request, self.template_name, context)
 
    def _handle_update(self, request):
        plan_id = request.POST.get("plan_id")
        plan = get_object_or_404(MembershipPlan, pk=plan_id)
        form = MembershipPlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, f"Plan '{plan.name}' updated successfully.")
            return redirect("membership-plans")
 
        messages.error(request, "Please correct the errors below and try again.")
        context = self._build_context(request, edit_form=form, open_modal="edit", edit_plan_id=plan.pk)
        return render(request, self.template_name, context)
 
    def _handle_delete(self, request):
        plan_id = request.POST.get("plan_id")
        plan = get_object_or_404(MembershipPlan, pk=plan_id)
        plan_name = plan.name
        plan.delete()
        messages.success(request, f"Plan '{plan_name}' deleted successfully.")
        return redirect("membership-plans")
 
    # ---------------------------------------------------------------
    # Shared context builder (GET + invalid-POST redisplay)
    # ---------------------------------------------------------------
 
    def _build_context(self, request, add_form=None, edit_form=None, open_modal=None, edit_plan_id=None):
        search_query = request.GET.get("q", "").strip()
        status_filter = request.GET.get("status", "")
        access_filter = request.GET.get("access_type", "")
 
        plans = MembershipPlan.objects.annotate(num_members=Count("members"))
 
        if search_query:
            plans = plans.filter(
                Q(name__icontains=search_query)
                | Q(plan_code__icontains=search_query)
                | Q(description__icontains=search_query)
            )
 
        if status_filter:
            plans = plans.filter(status=status_filter)
 
        if access_filter:
            plans = plans.filter(access_type=access_filter)
 
        # ---- Statistics (computed on the full, unfiltered table) ----
        all_plans = MembershipPlan.objects.all()
        total_plans = all_plans.count()
        active_plans = all_plans.filter(status=MembershipPlan.STATUS_ACTIVE).count()
        inactive_plans = all_plans.filter(status=MembershipPlan.STATUS_INACTIVE).count()
        premium_plans = all_plans.filter(
            access_type__in=[MembershipPlan.ACCESS_PREMIUM, MembershipPlan.ACCESS_VIP]
        ).count()
        avg_price = all_plans.aggregate(avg=Avg("price"))["avg"] or 0
 
        most_popular_plan = (
            MembershipPlan.objects.annotate(num_members=Count("members"))
            .order_by("-num_members")
            .first()
        )
        if most_popular_plan and most_popular_plan.num_members == 0:
            most_popular_plan = None
 
        page_number = request.GET.get("page", 1)
        plans_page = Paginator(plans, 10).get_page(page_number)

        return {
            "plans": plans_page,
            "add_form": add_form or MembershipPlanForm(),
            "edit_form": edit_form,
            "open_modal": open_modal,
            "edit_plan_id": edit_plan_id,
            "search_query": search_query,
            "status_filter": status_filter,
            "access_filter": access_filter,
            "status_choices": MembershipPlan.STATUS_CHOICES,
            "access_type_choices": MembershipPlan.ACCESS_TYPE_CHOICES,
            "duration_type_choices": MembershipPlan.DURATION_TYPE_CHOICES,
            # Stats
            "total_plans": total_plans,
            "active_plans": active_plans,
            "inactive_plans": inactive_plans,
            "premium_plans": premium_plans,
            "avg_price": round(avg_price, 2),
            "most_popular_plan": most_popular_plan,
        }


class CustomerRegistrationView(LoginRequiredMixin, View):
    """
    Single Class Based View inside the masters app handling the entire Customer Registration Module:
    - Member Registration Wizard (Steps 1 to 4 with dynamic membership plan selection & biometric enrollment)
    - Trainer Registration Wizard (Steps 1 to 3 with employment & biometric capture)
    - Customer & Trainer Directory (Search, Filter, View Details Modal, Edit Modal, Delete Modal)
    Strictly follows One CBV, One HTML, One URL per module.
    """

    template_name = "masters/customer_registration.html"
    login_url = "login"

    def get(self, request, *args, **kwargs):
        # Handle AJAX inspection requests for View/Edit Modals
        if request.GET.get("action") == "get_member":
            member = get_object_or_404(Member, pk=request.GET.get("id"))
            return JsonResponse({
                "id": member.pk,
                "member_id": member.member_id,
                "full_name": member.full_name,
                "dob": member.date_of_birth.strftime("%Y-%m-%d") if member.date_of_birth else "",
                "gender": member.gender,
                "blood_group": member.blood_group,
                "mobile_number": member.mobile_number,
                "email": member.email or "",
                "join_date": member.join_date.strftime("%Y-%m-%d") if member.join_date else "",
                "address": member.address or "",
                "height": member.height or "",
                "weight": member.weight or "",
                "fitness_goal": member.fitness_goal or "",
                "medical_condition": member.medical_condition or "",
                "membership_plan_id": member.membership_plan_id or "",
                "plan_name": member.membership_plan.name if member.membership_plan else "General Plan",
                "photo_url": member.photo.url if (member.photo and member.photo.name) else f"https://ui-avatars.com/api/?name={member.full_name}&background=2E6DA4&color=fff",
                "fingerprint_id": member.fingerprint_id or "",
                "membership_start_date": member.membership_start_date.strftime("%Y-%m-%d") if member.membership_start_date else "",
                "membership_end_date": member.membership_end_date.strftime("%Y-%m-%d") if member.membership_end_date else "",
                "is_active": member.is_active,
                "is_expired": member.is_expired,
            })

        if request.GET.get("action") == "get_trainer":
            trainer = get_object_or_404(Trainer, pk=request.GET.get("id"))
            return JsonResponse({
                "id": trainer.pk,
                "trainer_id": trainer.trainer_id,
                "full_name": trainer.full_name,
                "gender": trainer.gender,
                "mobile_number": trainer.mobile_number,
                "address": trainer.address or "",
                "photo_url": trainer.photo.url if (trainer.photo and trainer.photo.name) else f"https://ui-avatars.com/api/?name={trainer.full_name}&background=F7941D&color=fff",
                "designation": trainer.designation,
                "joining_date": trainer.joining_date.strftime("%Y-%m-%d") if trainer.joining_date else "",
                "salary": str(trainer.salary) if trainer.salary else "",
                "working_status": trainer.working_status,
                "working_time": trainer.working_time or "",
                "fingerprint_id": trainer.fingerprint_id or "",
            })

        search_query = request.GET.get("q", "").strip()
        tab = request.GET.get("tab", "wizard")

        members_qs = Member.objects.select_related("membership_plan").all()
        trainers_qs = Trainer.objects.all()

        if search_query:
            members_qs = members_qs.filter(
                Q(full_name__icontains=search_query) |
                Q(member_id__icontains=search_query) |
                Q(mobile_number__icontains=search_query)
            )
            trainers_qs = trainers_qs.filter(
                Q(full_name__icontains=search_query) |
                Q(trainer_id__icontains=search_query) |
                Q(mobile_number__icontains=search_query)
            )

        active_plans = MembershipPlan.objects.filter(is_active=True).order_by("display_order", "price")

        page_number = request.GET.get("page", 1)
        members_page = Paginator(members_qs, 10).get_page(page_number)
        trainers_page = Paginator(trainers_qs, 10).get_page(page_number)

        context = {
            "tab": tab,
            "search_query": search_query,
            "members": members_page,
            "trainers": trainers_page,
            "active_plans": active_plans,
            "member_form": MemberRegistrationForm(),
            "trainer_form": TrainerRegistrationForm(),
            "total_members_count": Member.objects.count(),
            "active_members_count": Member.objects.filter(is_active=True).count(),
            "total_trainers_count": Trainer.objects.count(),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")

        if action == "create_member":
            form = MemberRegistrationForm(request.POST, request.FILES)
            if form.is_valid():
                member = form.save(commit=False)
                plan = member.membership_plan
                start_date = member.join_date or timezone.localdate()
                member.membership_start_date = start_date

                if plan:
                    if plan.duration_type == MembershipPlan.DURATION_DAYS:
                        member.membership_end_date = start_date + timedelta(days=plan.duration)
                    elif plan.duration_type == MembershipPlan.DURATION_WEEKS:
                        member.membership_end_date = start_date + timedelta(weeks=plan.duration)
                    elif plan.duration_type == MembershipPlan.DURATION_MONTHS:
                        member.membership_end_date = start_date + timedelta(days=plan.duration * 30)
                    elif plan.duration_type == MembershipPlan.DURATION_YEARS:
                        member.membership_end_date = start_date + timedelta(days=plan.duration * 365)
                    else:
                        member.membership_end_date = start_date + timedelta(days=30)
                else:
                    member.membership_end_date = start_date + timedelta(days=30)

                member.save()
                messages.success(request, f"Member {member.full_name} ({member.member_id}) registered successfully!")
                return redirect("/customer-registration/?tab=members")
            else:
                for field, errs in form.errors.items():
                    messages.error(request, f"{field}: {errs[0]}")
                return redirect("/customer-registration/?tab=wizard")

        elif action == "update_member":
            member_pk = request.POST.get("member_pk")
            member = get_object_or_404(Member, pk=member_pk)
            form = MemberRegistrationForm(request.POST, request.FILES, instance=member)
            if form.is_valid():
                m = form.save(commit=False)
                # recalculate end date if plan changed
                plan = m.membership_plan
                start_date = m.membership_start_date or timezone.localdate()
                if plan and (not m.membership_end_date or "membership_plan" in form.changed_data):
                    if plan.duration_type == MembershipPlan.DURATION_DAYS:
                        m.membership_end_date = start_date + timedelta(days=plan.duration)
                    elif plan.duration_type == MembershipPlan.DURATION_WEEKS:
                        m.membership_end_date = start_date + timedelta(weeks=plan.duration)
                    elif plan.duration_type == MembershipPlan.DURATION_MONTHS:
                        m.membership_end_date = start_date + timedelta(days=plan.duration * 30)
                    elif plan.duration_type == MembershipPlan.DURATION_YEARS:
                        m.membership_end_date = start_date + timedelta(days=plan.duration * 365)
                m.save()
                messages.success(request, f"Member {m.full_name} updated successfully!")
            else:
                for field, errs in form.errors.items():
                    messages.error(request, f"{field}: {errs[0]}")
            return redirect("/customer-registration/?tab=members")

        elif action == "delete_member":
            member_pk = request.POST.get("member_pk")
            member = get_object_or_404(Member, pk=member_pk)
            name = member.full_name
            member.delete()
            messages.success(request, f"Member {name} deleted successfully.")
            return redirect("/customer-registration/?tab=members")

        elif action == "create_trainer":
            form = TrainerRegistrationForm(request.POST, request.FILES)
            if form.is_valid():
                trainer = form.save()
                messages.success(request, f"Trainer {trainer.full_name} ({trainer.trainer_id}) registered successfully!")
                return redirect("/customer-registration/?tab=trainers")
            else:
                for field, errs in form.errors.items():
                    messages.error(request, f"{field}: {errs[0]}")
                return redirect("/customer-registration/?tab=wizard")

        elif action == "update_trainer":
            trainer_pk = request.POST.get("trainer_pk")
            trainer = get_object_or_404(Trainer, pk=trainer_pk)
            form = TrainerRegistrationForm(request.POST, request.FILES, instance=trainer)
            if form.is_valid():
                form.save()
                messages.success(request, f"Trainer {trainer.full_name} updated successfully!")
            else:
                for field, errs in form.errors.items():
                    messages.error(request, f"{field}: {errs[0]}")
            return redirect("/customer-registration/?tab=trainers")

        elif action == "delete_trainer":
            trainer_pk = request.POST.get("trainer_pk")
            trainer = get_object_or_404(Trainer, pk=trainer_pk)
            name = trainer.full_name
            trainer.delete()
            messages.success(request, f"Trainer {name} deleted successfully.")
            return redirect("/customer-registration/?tab=trainers")

        messages.error(request, "Invalid action requested.")
        return redirect("/customer-registration/")

 