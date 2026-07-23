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
from .models import AccessType, MembershipPlan, Trainer, TrainerDesignation


class MembershipPlanView(LoginRequiredMixin, View):
    """
    Single Class Based View handling the entire Membership Plans module:
    listing, search, filtering, statistics, create, update and delete —
    all served from one URL and one template, using Bootstrap modals
    instead of separate pages.
    """

    template_name = "masters/membership-plans.html"
    login_url = "login"
    PLANS_PER_PAGE = 10

    # ---------------------------------------------------------------
    # GET — display page, stats, filtered/searched plan list
    # ---------------------------------------------------------------

    def get(self, request, *args, **kwargs):
        action = request.GET.get("action")
        if action == "list_access_types":
            return self._ajax_list_access_types(request)
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
        elif action == "toggle_status":
            return self._handle_toggle_status(request)
        # Change 3 — Access Type Master CRUD actions
        elif action == "create_access_type":
            return self._handle_create_access_type(request)
        elif action == "update_access_type":
            return self._handle_update_access_type(request)
        elif action == "delete_access_type":
            return self._handle_delete_access_type(request)

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
            messages.success(request, f"Membership plan '{plan.name}' created successfully.")
            return redirect("membership-plans")

        messages.error(request, "Please correct the errors below and try again.")
        context = self._build_context(request, add_form=form, open_modal="add")
        return render(request, self.template_name, context)

    def _handle_update(self, request):
        plan_id = request.POST.get("plan_id")
        plan = get_object_or_404(MembershipPlan, pk=plan_id)
        form = MembershipPlanForm(request.POST, instance=plan)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"Membership plan '{plan.name}' updated successfully.")
            return redirect("membership-plans")

        messages.error(request, "Please correct the errors below and try again.")
        context = self._build_context(
            request, edit_form=form, open_modal="edit", edit_plan_id=plan.pk, edit_plan_code=plan.plan_code
        )
        return render(request, self.template_name, context)

    def _handle_delete(self, request):
        plan_id = request.POST.get("plan_id")
        plan = get_object_or_404(MembershipPlan, pk=plan_id)
        # Protected Delete: a plan currently assigned to one or more active
        # members cannot be deleted — doing so would orphan their membership.
        # This mirrors the disabled/locked Delete button in the template and
        # guarantees the rule holds even if the request is forged.
        active_members = plan.members.filter(is_active=True).count()
        if active_members:
            messages.error(
                request,
                f"'{plan.name}' cannot be deleted while it is assigned to "
                f"{active_members} active member{'s' if active_members != 1 else ''}.",
            )
            return redirect("membership-plans")
        plan.delete()
        messages.success(request, f"Membership plan '{plan.name}' deleted successfully.")
        return redirect("membership-plans")

    def _handle_toggle_status(self, request):
        """
        AJAX-only handler for the Status capsule toggle in the table.
        Flips between Active and Inactive (a Draft plan is switched to
        Active on first click, matching the two states the toggle shows).
        Returns JSON so the row and the stat cards can update instantly
        without a full page reload.
        """
        plan_id = request.POST.get("plan_id")
        plan = get_object_or_404(MembershipPlan, pk=plan_id)

        if plan.status == MembershipPlan.STATUS_ACTIVE:
            plan.status = MembershipPlan.STATUS_INACTIVE
        else:
            plan.status = MembershipPlan.STATUS_ACTIVE
        plan.save()

        all_plans = MembershipPlan.objects.all()
        active_count = all_plans.filter(status=MembershipPlan.STATUS_ACTIVE).count()
        inactive_count = all_plans.filter(status=MembershipPlan.STATUS_INACTIVE).count()

        return JsonResponse({
            "ok": True,
            "status": plan.status,
            "status_display": plan.get_status_display(),
            "active_plans": active_count,
            "inactive_plans": inactive_count,
        })

    # ---------------------------------------------------------------
    # Shared context builder (GET + invalid-POST redisplay)
    # ---------------------------------------------------------------

    def _build_context(
        self, request, add_form=None, edit_form=None, open_modal=None, edit_plan_id=None, edit_plan_code=None,
        open_access_type_modal=False,
    ):
        # Ensure default access types exist (idempotent, fast on repeat calls).
        AccessType.ensure_defaults()

        search_query = request.GET.get("q", "").strip()
        status_filter = request.GET.get("status", "")
        access_filter = request.GET.get("access_type", "")
        page_number = request.GET.get("page", 1)

        plans = MembershipPlan.objects.annotate(
            num_members=Count("members"),
            active_member_count=Count("members", filter=Q(members__is_active=True)),
        ).order_by("-created_at")

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

        paginator = None
        if search_query:
            plans_page = plans
        else:
            paginator = Paginator(plans, self.PLANS_PER_PAGE)
            plans_page = paginator.get_page(page_number)

        base_query_params = request.GET.copy()
        base_query_params.pop("page", None)
        base_query_string = base_query_params.urlencode()

        all_plans = MembershipPlan.objects.all()
        total_plans = all_plans.count()
        active_plans = all_plans.filter(status=MembershipPlan.STATUS_ACTIVE).count()
        inactive_plans = all_plans.filter(status=MembershipPlan.STATUS_INACTIVE).count()

        # Premium/VIP plan count — uses slugs from master table
        premium_slugs = list(
            AccessType.objects.filter(
                slug__in=[MembershipPlan.ACCESS_PREMIUM, MembershipPlan.ACCESS_VIP]
            ).values_list("slug", flat=True)
        )
        if not premium_slugs:  # fallback if master not seeded yet
            premium_slugs = [MembershipPlan.ACCESS_PREMIUM, MembershipPlan.ACCESS_VIP]
        premium_plans = all_plans.filter(access_type__in=premium_slugs).count()

        avg_price = all_plans.aggregate(avg=Avg("price"))["avg"] or 0

        most_popular_plan = (
            MembershipPlan.objects.annotate(num_members=Count("members"))
            .order_by("-num_members")
            .first()
        )
        if most_popular_plan and most_popular_plan.num_members == 0:
            most_popular_plan = None

        # Build access_type_choices from master table (active types only).
        # Falls back to hardcoded list if master table is empty.
        access_types_qs = AccessType.objects.filter(is_active=True).order_by("display_order", "name")
        access_type_choices_dynamic = [(at.slug, at.name) for at in access_types_qs]
        access_type_choices = access_type_choices_dynamic or list(MembershipPlan.ACCESS_TYPE_CHOICES)

        return {
            "plans": plans_page,
            "paginator": paginator,
            "base_query_string": base_query_string,
            "add_form": add_form or MembershipPlanForm(),
            "edit_form": edit_form,
            "open_modal": open_modal,
            "open_access_type_modal": open_access_type_modal,
            "edit_plan_id": edit_plan_id,
            "edit_plan_code": edit_plan_code,
            "search_query": search_query,
            "status_filter": status_filter,
            "access_filter": access_filter,
            "status_choices": MembershipPlan.STATUS_CHOICES,
            "access_type_choices": access_type_choices,
            "access_types": access_types_qs,
            "all_access_types": AccessType.objects.all().order_by("display_order", "name"),
            "duration_type_choices": MembershipPlan.DURATION_TYPE_CHOICES,
            "total_plans": total_plans,
            "active_plans": active_plans,
            "inactive_plans": inactive_plans,
            "premium_plans": premium_plans,
            "avg_price": round(avg_price, 2),
            "most_popular_plan": most_popular_plan,
        }

    # ---------------------------------------------------------------
    # Change 3 — Access Type Master CRUD handlers (AJAX/JSON)
    # ---------------------------------------------------------------

    def _ajax_list_access_types(self, request):
        """Return all access types as JSON for client-side refresh."""
        types = [
            {
                "id": at.id,
                "slug": at.slug,
                "name": at.name,
                "icon": at.icon,
                "description": at.description,
                "is_active": at.is_active,
                "display_order": at.display_order,
                "is_used": at.is_used,
            }
            for at in AccessType.objects.all().order_by("display_order", "name")
        ]
        return JsonResponse({"ok": True, "access_types": types})

    def _handle_create_access_type(self, request):
        """
        Create a new Access Type from the "Access Type Master" modal.
        Returns JSON so the modal list can refresh without a full page reload.
        """
        import re
        name = request.POST.get("at_name", "").strip()
        icon = request.POST.get("at_icon", "bi-door-open").strip() or "bi-door-open"
        description = request.POST.get("at_description", "").strip()
        display_order = request.POST.get("at_display_order", 0)

        if not name:
            return JsonResponse({"ok": False, "error": "Access Type name is required."})
        if len(name) > 60:
            return JsonResponse({"ok": False, "error": "Name must be 60 characters or fewer."})
        if AccessType.objects.filter(name__iexact=name).exists():
            return JsonResponse({"ok": False, "error": f"An access type named ‘{name}’ already exists."})

        # Auto-generate slug from name
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30]
        # Ensure slug uniqueness
        base_slug, counter = slug, 1
        while AccessType.objects.filter(slug=slug).exists():
            slug = f"{base_slug[:27]}-{counter}"
            counter += 1

        try:
            display_order = int(display_order)
        except (TypeError, ValueError):
            display_order = 0

        at = AccessType.objects.create(
            slug=slug, name=name, icon=icon,
            description=description, display_order=display_order, is_active=True,
        )
        return JsonResponse({
            "ok": True,
            "id": at.id,
            "slug": at.slug,
            "name": at.name,
            "icon": at.icon,
            "description": at.description,
            "display_order": at.display_order,
            "is_active": at.is_active,
            "is_used": False,
        })

    def _handle_update_access_type(self, request):
        """Update an existing Access Type. Returns JSON."""
        at_id = request.POST.get("at_id")
        at = get_object_or_404(AccessType, pk=at_id)

        name = request.POST.get("at_name", "").strip()
        icon = request.POST.get("at_icon", at.icon).strip() or at.icon
        description = request.POST.get("at_description", "").strip()
        display_order = request.POST.get("at_display_order", at.display_order)
        is_active = request.POST.get("at_is_active", "true").lower() not in ("false", "0", "")

        if not name:
            return JsonResponse({"ok": False, "error": "Access Type name is required."})
        if len(name) > 60:
            return JsonResponse({"ok": False, "error": "Name must be 60 characters or fewer."})
        if AccessType.objects.filter(name__iexact=name).exclude(pk=at.pk).exists():
            return JsonResponse({"ok": False, "error": f"An access type named ‘{name}’ already exists."})

        try:
            display_order = int(display_order)
        except (TypeError, ValueError):
            display_order = at.display_order

        at.name = name
        at.icon = icon
        at.description = description
        at.display_order = display_order
        at.is_active = is_active
        at.save()
        return JsonResponse({
            "ok": True,
            "id": at.id,
            "slug": at.slug,
            "name": at.name,
            "icon": at.icon,
            "description": at.description,
            "display_order": at.display_order,
            "is_active": at.is_active,
            "is_used": at.is_used,
        })

    def _handle_delete_access_type(self, request):
        """
        Delete an Access Type. Protected — types in use by at least one plan
        cannot be deleted (mirrors the plan-delete protection for plans with members).
        """
        at_id = request.POST.get("at_id")
        at = get_object_or_404(AccessType, pk=at_id)

        if at.is_used:
            plan_count = MembershipPlan.objects.filter(access_type=at.slug).count()
            return JsonResponse({
                "ok": False,
                "error": (
                    f"‘{at.name}’ cannot be deleted — it is currently used by "
                    f"{plan_count} membership plan{'s' if plan_count != 1 else ''}. "
                    "Reassign or delete those plans first."
                ),
            })

        at.delete()
        return JsonResponse({"ok": True})


class CustomerRegistrationView(LoginRequiredMixin, View):
    """
    Single Class Based View inside the masters app handling the entire Customer
    Registration Module:
      - Member Registration Wizard (3 steps: Basic Info, Health, Membership)
      - Trainer Registration Wizard (2 steps: Basic Info, Employment)
      - Customer & Trainer Directory (live client-side search + pagination,
        View Details modal, Edit modal, Delete modal, Active/Inactive capsule)

    The standalone Biometric Wizard step has been removed entirely for both
    wizards. A `biometric_id` PIN is generated automatically by the model's
    `save()` and is only ever *displayed* (read-only) inside Basic Information
    and the directory "View" modal.

    Strictly follows One CBV, One HTML, One URL per module.
    """

    template_name = "masters/customer_registration.html"
    login_url = "login"

    # -----------------------------------------------------------------
    # GET
    # -----------------------------------------------------------------

    def get(self, request, *args, **kwargs):
        # ---- AJAX inspection requests for View/Edit Modals ----
        if request.GET.get("action") == "get_member":
            return self._get_member_json(request)

        if request.GET.get("action") == "get_trainer":
            return self._get_trainer_json(request)

        tab = request.GET.get("tab", "wizard")

        # Full querysets are handed to the template; pagination (10/page) and
        # live search (across *all* records, ignoring pagination while
        # active) are both handled client-side in JS so search never has to
        # round-trip to the server. See customer_registration.js.
        # Annotate each record with its Reports-module attendance count so the
        # directory can lock the Delete button (Protected Delete) for anyone
        # who already has history in Reports.
        members_qs = (
            Member.objects.select_related("membership_plan")
            .annotate(report_record_count=Count("attendance_records"))
            .order_by("-created_at" if hasattr(Member, "created_at") else "-pk")
        )
        trainers_qs = (
            Trainer.objects.annotate(
                report_record_count=Count("trainer_attendance_records")
            ).order_by("-joining_date", "full_name")
        )

        active_plans = MembershipPlan.objects.filter(is_active=True).order_by("display_order", "price")
        TrainerDesignation.ensure_defaults()

        context = {
            "tab": tab,
            "members": members_qs,
            "trainers": trainers_qs,
            "active_plans": active_plans,
            "member_form": MemberRegistrationForm(initial={"join_date": timezone.localdate()}),
            "trainer_form": TrainerRegistrationForm(initial={"joining_date": timezone.localdate()}),
            "total_members_count": Member.objects.count(),
            "active_members_count": Member.objects.filter(is_active=True).count(),
            "total_trainers_count": Trainer.objects.count(),
            "designations": TrainerDesignation.objects.filter(is_active=True).order_by("name"),
        }
        return render(request, self.template_name, context)

    def _get_member_json(self, request):
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
            "username": getattr(member, "username", "") or "",
            "join_date": member.join_date.strftime("%Y-%m-%d") if member.join_date else "",
            "address": member.address or "",
            "height": member.height or "",
            "weight": member.weight or "",
            "bmi": str(member.bmi) if member.bmi is not None else "",
            "fitness_goal": member.fitness_goal or "",
            "medical_condition": member.medical_condition or "",
            "membership_plan_id": member.membership_plan_id or "",
            "plan_name": member.membership_plan.name if member.membership_plan else "General Plan",
            "plan_amount": float(member.membership_plan.final_price if member.membership_plan and hasattr(member.membership_plan, 'final_price') and member.membership_plan.final_price else (member.membership_plan.price if member.membership_plan else 0.0)),
            "amount_paid": float(member.amount_paid or 0.0),
            "remaining_amount": max(0.0, float(member.membership_plan.final_price if member.membership_plan and hasattr(member.membership_plan, 'final_price') and member.membership_plan.final_price else (member.membership_plan.price if member.membership_plan else 0.0)) - float(member.amount_paid or 0.0)),
            "photo_url": member.photo.url if member.photo else f"https://ui-avatars.com/api/?name={member.full_name}&background=2E6DA4&color=fff",
            "has_photo": bool(member.photo),
            "biometric_id": getattr(member, "biometric_id", "") or "Not yet generated",
            "membership_start_date": member.membership_start_date.strftime("%Y-%m-%d") if member.membership_start_date else "",
            "membership_end_date": member.membership_end_date.strftime("%Y-%m-%d") if member.membership_end_date else "",
            "is_active": member.is_active,
            "is_expired": member.is_expired,
        })

    def _get_trainer_json(self, request):
        trainer = get_object_or_404(Trainer, pk=request.GET.get("id"))
        return JsonResponse({
            "id": trainer.pk,
            "trainer_id": trainer.trainer_id,
            "full_name": trainer.full_name,
            "gender": trainer.gender,
            "date_of_birth": trainer.date_of_birth.strftime("%Y-%m-%d") if trainer.date_of_birth else "",
            "blood_group": trainer.blood_group or "",
            "email": trainer.email or "",
            "mobile_number": trainer.mobile_number,
            "username": trainer.username,
            "address": trainer.address or "",
            "photo_url": trainer.photo.url if trainer.photo else f"https://ui-avatars.com/api/?name={trainer.full_name}&background=F7941D&color=fff",
            "has_photo": bool(trainer.photo),
            "designation": trainer.designation,
            "joining_date": trainer.joining_date.strftime("%Y-%m-%d") if trainer.joining_date else "",
            "salary": str(trainer.salary) if trainer.salary else "",
            "working_status": trainer.working_status,
            "working_time": trainer.working_time or "",
            "biometric_id": trainer.biometric_id or "Not yet generated",
            "is_active": trainer.is_active,
        })

    # -----------------------------------------------------------------
    # POST
    # -----------------------------------------------------------------

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")

        handler_map = {
            "create_member": self._create_member,
            "update_member": self._update_member,
            "delete_member": self._delete_member,
            "toggle_status_member": self._toggle_status_member,
            "create_trainer": self._create_trainer,
            "update_trainer": self._update_trainer,
            "delete_trainer": self._delete_trainer,
            "toggle_status_trainer": self._toggle_status_trainer,
            "add_designation": self._add_designation,
            "edit_designation": self._edit_designation,
            "delete_designation": self._delete_designation,
        }
        handler = handler_map.get(action)
        if handler:
            return handler(request)

        return redirect("/customer-registration/")

    # ---------------------------------------------------------------
    # Members
    # ---------------------------------------------------------------

    def _apply_plan_dates(self, member, form_changed_data=None):
        plan = member.membership_plan
        # Expiry must always be derived from the Joining Date the operator
        # selected at registration — NOT the current date. The model default
        # for membership_start_date is today, so we intentionally anchor the
        # start date to join_date first and keep membership_start_date in sync
        # with it. This is the root cause fix for "expiry counts from today".
        start_date = member.join_date or member.membership_start_date or timezone.localdate()
        member.membership_start_date = start_date

        should_recalc = (
            form_changed_data is None
            or not member.membership_end_date
            or "membership_plan" in form_changed_data
            or "join_date" in form_changed_data
        )
        if not should_recalc:
            return

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

    def _create_member(self, request):
        # Photo is optional at registration time (Change 2B).
        form = MemberRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            member = form.save(commit=False)
            self._apply_plan_dates(member, form_changed_data=None)
            member.save()
            messages.success(request, f"Member {member.full_name} registered successfully.")
            return redirect("/customer-registration/?tab=members")

        # Surface specific server-side validation errors (e.g. duplicate
        # mobile number / email) so the operator gets a clear reason rather
        # than a silent bounce back to the wizard.
        for field, errors in form.errors.items():
            for error in errors:
                prefix = f"{form.fields[field].label}: " if field != "__all__" and field in form.fields else ""
                messages.error(request, f"{prefix}{error}")
        return redirect("/customer-registration/?tab=wizard")

    def _update_member(self, request):
        member_pk = request.POST.get("member_pk")
        member = get_object_or_404(Member, pk=member_pk)

        # item 22 — explicit "remove photo" support in the Edit modal
        remove_photo = request.POST.get("remove_photo") == "1"

        # A blank Reset PIN / Username field in the Edit modal means "keep
        # the existing value" — it must never be treated as "clear it".
        posted_pin = (request.POST.get("pin") or "").strip()
        posted_username = (request.POST.get("username") or "").strip()

        form = MemberRegistrationForm(request.POST, request.FILES, instance=member)
        if "photo" in form.fields:
            form.fields["photo"].required = False
        if "pin" in form.fields:
            form.fields["pin"].required = False
        if "username" in form.fields:
            form.fields["username"].required = False
        # The Edit modal intentionally doesn't expose Join Date — but the
        # form field is required (the model default doesn't relax the form
        # requirement). Leaving it required made every edit fail validation
        # ("Could not save member changes"). Make it optional here and keep
        # the member's existing join_date when the field isn't submitted.
        if "join_date" in form.fields:
            form.fields["join_date"].required = False

        if form.is_valid():
            m = form.save(commit=False)
            if not m.join_date:
                m.join_date = member.join_date
            if remove_photo and not request.FILES.get("photo"):
                m.photo.delete(save=False)
                m.photo = None
            if not posted_pin:
                # `member.pin` was never a real attribute on this model
                # (only `password_pin` is) — reading it raised an
                # AttributeError on every save that left the PIN blank,
                # which aborted the request before m.save() ever ran.
                m.password_pin = member.password_pin
            if not posted_username:
                m.username = member.username
            self._apply_plan_dates(m, form_changed_data=form.changed_data)
            m.save()
            messages.success(request, "Member details updated successfully.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    prefix = f"{form.fields[field].label}: " if field != "__all__" and field in form.fields else ""
                    messages.error(request, f"{prefix}{error}")
        return redirect("/customer-registration/?tab=members")

    def _delete_member(self, request):
        member_pk = request.POST.get("member_pk")
        member = get_object_or_404(Member, pk=member_pk)
        # Protected Delete: a member who already has attendance history in the
        # Reports module must be preserved so those reports stay intact. This
        # backs the disabled/locked Delete button in the directory and blocks
        # forged requests too.
        report_records = member.attendance_records.count()
        if report_records:
            messages.error(
                request,
                f"{member.full_name} cannot be deleted — {report_records} "
                f"attendance record{'s' if report_records != 1 else ''} exist in Reports.",
            )
            return redirect("/customer-registration/?tab=members")
        member.delete()
        messages.success(request, f"Member {member.full_name} deleted successfully.")
        return redirect("/customer-registration/?tab=members")

    def _toggle_status_member(self, request):
        """AJAX-only handler for the Active/Inactive capsule in the Members Directory."""
        member_pk = request.POST.get("member_pk")
        member = get_object_or_404(Member, pk=member_pk)
        member.is_active = not member.is_active
        member.save(update_fields=["is_active"])
        return JsonResponse({
            "ok": True,
            "is_active": member.is_active,
            "status_display": "Active" if member.is_active else "Inactive",
        })

    # ---------------------------------------------------------------
    # Trainers
    # ---------------------------------------------------------------

    def _create_trainer(self, request):
        # Photo is optional at registration time (Change 2B).
        form = TrainerRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Trainer registered successfully.")
            return redirect("/customer-registration/?tab=trainers")

        for field, errors in form.errors.items():
            for error in errors:
                # Use field name in the error message if it's not a non-field error
                prefix = f"{form.fields[field].label}: " if field != "__all__" and field in form.fields else ""
                messages.error(request, f"{prefix}{error}")
        return redirect("/customer-registration/?tab=wizard")

    def _update_trainer(self, request):
        trainer_pk = request.POST.get("trainer_pk")
        trainer = get_object_or_404(Trainer, pk=trainer_pk)
        remove_photo = request.POST.get("remove_photo") == "1"

        # A blank Reset PIN / Username field in the Edit modal means "keep
        # the existing value" — it must never be treated as "clear it".
        posted_pin = (request.POST.get("pin") or "").strip()
        posted_username = (request.POST.get("username") or "").strip()

        form = TrainerRegistrationForm(request.POST, request.FILES, instance=trainer)
        # Photo must NOT be required on edit — only required at registration.
        # Leaving it required blocked every edit that didn't re-upload a
        # photo, which is why edits (including photo replacement) silently
        # failed to save at all.
        if "photo" in form.fields:
            form.fields["photo"].required = False
        if "pin" in form.fields:
            form.fields["pin"].required = False
        if "username" in form.fields:
            form.fields["username"].required = False

        if form.is_valid():
            t = form.save(commit=False)
            if remove_photo and not request.FILES.get("photo"):
                t.photo.delete(save=False)
                t.photo = None
            if not posted_pin:
                # `trainer.pin` was never a real attribute on this model
                # (only `password_pin` is) — reading it raised an
                # AttributeError on every save that left the PIN blank,
                # which aborted the request before t.save() ever ran.
                t.password_pin = trainer.password_pin
            if not posted_username:
                t.username = trainer.username
            t.save()
            messages.success(request, "Trainer details updated successfully.")
        else:
            messages.error(request, "Could not save trainer changes — please check the form and try again.")
        return redirect("/customer-registration/?tab=trainers")

    def _delete_trainer(self, request):
        trainer_pk = request.POST.get("trainer_pk")
        trainer = get_object_or_404(Trainer, pk=trainer_pk)
        # Protected Delete: a trainer with attendance history in the Reports
        # module must be preserved so those reports stay intact.
        report_records = trainer.trainer_attendance_records.count()
        if report_records:
            messages.error(
                request,
                f"{trainer.full_name} cannot be deleted — {report_records} "
                f"attendance record{'s' if report_records != 1 else ''} exist in Reports.",
            )
            return redirect("/customer-registration/?tab=trainers")
        trainer.delete()
        messages.success(request, f"Trainer {trainer.full_name} deleted successfully.")
        return redirect("/customer-registration/?tab=trainers")

    def _toggle_status_trainer(self, request):
        """
        AJAX-only handler for the Active/Inactive capsule in the Trainers Directory.
        """
        trainer_pk = request.POST.get("trainer_pk")
        trainer = get_object_or_404(Trainer, pk=trainer_pk)
        if trainer.is_active:
            trainer.working_status = Trainer.STATUS_LEFT
        else:
            trainer.working_status = Trainer.STATUS_PERMANENT
        trainer.save(update_fields=["working_status"])
        return JsonResponse({
            "ok": True,
            "is_active": trainer.is_active,
            "status_display": "Active" if trainer.is_active else "Inactive",
        })

    # ---------------------------------------------------------------
    # Trainer Designation Master (item 11)
    # ---------------------------------------------------------------

    def _add_designation(self, request):
        name = request.POST.get("designation_name", "").strip()
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

        if not name:
            if is_ajax:
                return JsonResponse({"ok": False, "error": "Designation name is required."}, status=400)
            return redirect("/customer-registration/?tab=wizard")

        designation, created = TrainerDesignation.objects.get_or_create(name=name)
        if not created:
            if is_ajax:
                return JsonResponse({"ok": False, "error": "This designation already exists."}, status=400)
            return redirect("/customer-registration/?tab=wizard")

        if is_ajax:
            return JsonResponse({"ok": True, "id": designation.pk, "name": designation.name})
        return redirect("/customer-registration/?tab=wizard")

    def _edit_designation(self, request):
        """Rename a designation. Any trainer currently carrying the old
        name (a plain CharField, not a FK) is kept in sync automatically."""
        designation_id = request.POST.get("designation_id")
        new_name = request.POST.get("designation_name", "").strip()
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        designation = get_object_or_404(TrainerDesignation, pk=designation_id)

        if not new_name:
            error = "Designation name is required."
            if is_ajax:
                return JsonResponse({"ok": False, "error": error}, status=400)
            messages.error(request, error)
            return redirect("/customer-registration/?tab=wizard")

        if TrainerDesignation.objects.filter(name__iexact=new_name).exclude(pk=designation.pk).exists():
            error = "Another designation with this name already exists."
            if is_ajax:
                return JsonResponse({"ok": False, "error": error}, status=400)
            messages.error(request, error)
            return redirect("/customer-registration/?tab=wizard")

        old_name = designation.name
        designation.name = new_name
        designation.save(update_fields=["name"])
        Trainer.objects.filter(designation=old_name).update(designation=new_name)

        if is_ajax:
            return JsonResponse({"ok": True, "id": designation.pk, "old_name": old_name, "name": designation.name})
        return redirect("/customer-registration/?tab=wizard")

    def _delete_designation(self, request):
        """Soft-deletes via is_active=False (the field already existed for
        exactly this purpose). Refuses to remove a designation still in use
        by a trainer, since it's a required field on Trainer."""
        designation_id = request.POST.get("designation_id")
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        designation = get_object_or_404(TrainerDesignation, pk=designation_id)

        if Trainer.objects.filter(designation=designation.name).exists():
            error = "This designation is assigned to one or more trainers and can't be removed. Reassign those trainers first."
            if is_ajax:
                return JsonResponse({"ok": False, "error": error}, status=400)
            messages.error(request, error)
            return redirect("/customer-registration/?tab=wizard")

        designation.is_active = False
        designation.save(update_fields=["is_active"])

        if is_ajax:
            return JsonResponse({"ok": True, "id": designation.pk})
        return redirect("/customer-registration/?tab=wizard")