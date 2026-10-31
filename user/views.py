"""
Views for the user app, handling user management, authentication,
sessions, and related data like salaries and transactions.
"""

import logging
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.db.models import Exists, Max, OuterRef, Prefetch, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic.edit import CreateView, DeleteView, UpdateView

from base.getDates import getDates
from base.utility import (
    build_search_filter,
    parse_flexible_date,
    render_paginated_response,
    table_sorting,
)

from base.decorators import RequiredPermissionMixin, required_permission

from invoice.models import Invoice, InvoiceItem

from .forms import CustomUserForm, PasswordResetForm, SalaryForm, TransactionForm
from .models import Salary, Transaction
from .services import CommissionService

logger = logging.getLogger(__name__)

User = get_user_model()

VALID_SORT_FIELDS = {
    "id": "id",
    "full_name": "first_name",
    "phone_number": "phone_number",
    "email": "email",
    "address": "address",
    "date_joined": "date_joined",
}

USERS_PER_PAGE = 20


@required_permission("user.view_customuser")
def home(request):
    """User management main page - initial load only."""
    groups = Group.objects.all().order_by("name")
    max_sal = (
        Salary.objects.filter(effective_to__isnull=True).aggregate(Max("amount"))["amount__max"]
    )
    slider_max_salary = int(max_sal * Decimal("1.2")) if max_sal and max_sal > 0 else 50000
    slider_max_salary = max(slider_max_salary, 50000)

    context = {
        "groups": groups,
        "slider_max_salary": slider_max_salary,
    }
    return render(request, "user/home.html", context)


def get_data(request):
    """Helper function to get filtered and sorted users."""
    # Get search and filter parameters
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()
    group_filter = request.GET.get("group", "").strip()
    staff_status = request.GET.get("staff_status", "").strip()
    commission_filter = request.GET.get("commission", "").strip()
    has_email = request.GET.get("has_email", "").strip()
    has_salary = request.GET.get("has_salary", "").strip()
    min_salary = request.GET.get("min_salary", "").strip()
    max_salary = request.GET.get("max_salary", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    # Apply search filter across real model fields
    filters = build_search_filter(
        search_query,
        ["first_name", "last_name", "phone_number", "email", "address", "profile_id"],
    )

    # Status filter (active/inactive)
    if status_filter == "active":
        filters &= Q(is_active=True)
    elif status_filter == "inactive":
        filters &= Q(is_active=False)

    # Group / Role filter
    if group_filter:
        if group_filter.isdigit():
            filters &= Q(groups__id=int(group_filter))
        else:
            filters &= Q(groups__name__iexact=group_filter)

    # Staff / Superuser filter
    if staff_status == "staff":
        filters &= Q(is_staff=True)
    elif staff_status == "superuser":
        filters &= Q(is_superuser=True)
    elif staff_status == "regular":
        filters &= Q(is_staff=False, is_superuser=False)

    # Apply commission filter (check current salary's commission and active status)
    if commission_filter == "yes":
        # Users with current salary (effective_to is null) AND commission=True AND is_active=True
        filters &= Q(salaries__effective_to__isnull=True, salaries__commission=True, is_active=True)
    elif commission_filter == "no":
        # Users with no current salary OR current salary with commission=False OR is_active=False
        # Exclude active users who have current salary with commission=True
        from .models import (
            Salary as SalaryModel,
        )  # pylint: disable=redefined-outer-name

        has_commission = SalaryModel.objects.filter(
            user=OuterRef("pk"), effective_to__isnull=True, commission=True, user__is_active=True
        )
        filters &= ~Exists(has_commission)

    # Has email toggle
    if has_email in ("1", "true", "yes"):
        filters &= Q(email__isnull=False) & ~Q(email="")

    # Has active salary toggle
    if has_salary in ("1", "true", "yes"):
        filters &= Q(salaries__effective_to__isnull=True)

    # Salary range filter
    if min_salary:
        try:
            filters &= Q(
                salaries__effective_to__isnull=True,
                salaries__amount__gte=Decimal(min_salary),
            )
        except (ValueError, ArithmeticError):
            pass

    if max_salary:
        try:
            filters &= Q(
                salaries__effective_to__isnull=True,
                salaries__amount__lte=Decimal(max_salary),
            )
        except (ValueError, ArithmeticError):
            pass

    # Date joined range
    if date_from:
        d_from = parse_flexible_date(date_from)
        if d_from:
            filters &= Q(date_joined__date__gte=d_from)

    if date_to:
        d_to = parse_flexible_date(date_to)
        if d_to:
            filters &= Q(date_joined__date__lte=d_to)

    valid_sorts = table_sorting(request, VALID_SORT_FIELDS, "-date_joined")
    users = (
        User.objects.filter(filters)
        .distinct()
        .prefetch_related(
            "groups",
            Prefetch(
                "salaries",
                queryset=Salary.objects.filter(effective_to__isnull=True),
                to_attr="current_salaries",
            ),
        )
        .order_by(*valid_sorts)
    )

    return users


@required_permission("user.view_customuser")
def fetch_users(request):
    """AJAX endpoint to fetch users with search, filter, and pagination."""
    users = get_data(request)

    return render_paginated_response(
        request,
        users,
        "user/fetch.html",
    )


class CreateUser(RequiredPermissionMixin, CreateView):
    """View to create a new user."""

    required_permission = "user.add_customuser"
    model = User
    form_class = CustomUserForm
    template_name = "user/form.html"
    success_url = reverse_lazy("user:home")

    def form_valid(self, form):
        from django.utils.crypto import get_random_string

        user = form.save(commit=False)
        user.set_password(get_random_string(length=24))
        user.save()
        messages.success(self.request, "User created successfully!")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create User"
        context["user"] = None  # For breadcrumb compatibility
        return context

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class EditUser(RequiredPermissionMixin, UpdateView):
    """View to edit an existing user."""

    required_permission = "user.change_customuser"
    model = User
    form_class = CustomUserForm
    template_name = "user/form.html"
    success_url = reverse_lazy("user:home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Edit User"
        context["user"] = self.get_object()  # For breadcrumb compatibility
        return context

    def form_valid(self, form):
        messages.success(self.request, "User updated successfully!")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class DeleteUser(RequiredPermissionMixin, DeleteView):
    """View to delete a user."""

    required_permission = "user.delete_customuser"
    model = User
    template_name = "user/delete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["user"] = self.get_object()
        return context

    def delete(self, request, *args, **kwargs):
        user = self.get_object()
        messages.success(request, f"User '{user.full_name}' deleted successfully!")
        return super().delete(request, *args, **kwargs)

    def get_success_url(self):
        return reverse_lazy("user:home")

    def form_valid(self, form):
        messages.success(self.request, "User deleted successfully!")
        return super().form_valid(form)

    def form_invalid(self, form):
        logger.error("Form invalid: %s", form.errors)
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


@required_permission("user.view_customuser")
def user_detail(request, pk):
    """View user details."""
    user = get_object_or_404(User, id=pk)

    salaries = user.salaries.all()[:50]  # Last 50 salary records
    transactions = user.transactions.all().order_by("-date")[
        :50
    ]  # Last 50 transactions
    current_salary = user.current_salary

    # Calculate summary statistics
    total_salaries = user.salaries.count()
    total_transactions = user.transactions.count()

    # Calculate transaction totals
    credit_transactions = user.transactions.filter(
        transaction_type__in=[
            Transaction.TransactionType.SALE,
            Transaction.TransactionType.DEPOSIT,
            Transaction.TransactionType.PAYMENT,
            Transaction.TransactionType.COMMISSION,
            Transaction.TransactionType.SALARY,
        ]
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    debit_transactions = user.transactions.filter(
        transaction_type__in=[
            Transaction.TransactionType.REFUND,
            Transaction.TransactionType.WITHDRAWAL,
            Transaction.TransactionType.EXPENSE,
        ]
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    net_amount = credit_transactions - debit_transactions

    return render(
        request,
        "user/detail.html",
        {
            "user": user,
            "salaries": salaries,
            "transactions": transactions,
            "current_salary": current_salary,
            "total_salaries": total_salaries,
            "total_transactions": total_transactions,
            "credit_transactions": credit_transactions,
            "debit_transactions": debit_transactions,
            "net_amount": net_amount,
        },
    )


@required_permission("user.delete_customuser")
def user_delete(request, user_id):
    """Delete user."""
    if request.method == "POST":
        user = get_object_or_404(User, id=user_id)
        user.delete()
        messages.success(request, "User deleted successfully!")
        return redirect("user:home")

    return redirect("user:home")


def search_users_ajax(request):
    """AJAX endpoint for real-time user search."""
    search_query = request.GET.get("q", "")

    if len(search_query) < 2:
        return JsonResponse({"users": []})

    users = User.objects.filter(
        Q(full_name__icontains=search_query)
        | Q(phone_number__icontains=search_query)
        | Q(email__icontains=search_query)
        | Q(address__icontains=search_query)
    )[
        :10
    ]  # Limit to 10 results

    data = []
    for user in users:
        data.append(
            {
                "id": user.id,
                "full_name": user.full_name,
                "phone_number": user.phone_number,
                "email": user.email,
                "is_active": user.is_active,
            }
        )

    return JsonResponse({"users": data})


@required_permission("user.change_customuser")
def change_user_status(request, user_id):
    """Toggle user active/inactive status."""
    if request.method == "POST":
        user = get_object_or_404(User, id=user_id)
        user.is_active = not user.is_active
        user.save()

        status = "activated" if user.is_active else "deactivated"
        messages.success(request, f"User '{user.full_name}' {status} successfully!")

        return redirect("user:home")

    return redirect("user:home")


def sessions_overview(request):
    """List active sessions and users' last login details."""
    from django.conf import settings
    from importlib import import_module
    
    now = timezone.now()
    sessions_data = []
    active_count = 0
    session_key_to_is_current = (
        {request.session.session_key: True} if request.session.session_key else {}
    )

    if settings.SESSION_ENGINE in ["django.contrib.sessions.backends.db", "django.contrib.sessions.backends.cached_db"]:
        active_sessions = list(Session.objects.filter(expire_date__gt=now))
        active_count = len(active_sessions)
        
        decoded_sessions = []
        user_ids = set()
        for session in active_sessions:
            data = session.get_decoded()
            user_id = data.get("_auth_user_id")
            if user_id:
                user_ids.add(user_id)
                decoded_sessions.append((session, data, str(user_id)))

        users_by_id = {str(u.id): u for u in User.objects.filter(id__in=user_ids)}

        for session, data, user_id in decoded_sessions:
            user = users_by_id.get(user_id)
            if not user:
                continue

            sessions_data.append(
                {
                    "session_key": session.session_key,
                    "user": user,
                    "last_login": user.last_login,
                    "expire_date": session.expire_date,
                    "is_current": session_key_to_is_current.get(session.session_key, False),
                    "ip_address": data.get("ip_address"),
                    "user_agent": data.get("user_agent"),
                    "last_activity": data.get("last_activity"),
                }
            )
            
    elif settings.SESSION_ENGINE == "django.contrib.sessions.backends.cache":
        from django.core.cache import caches
        cache = caches[settings.SESSION_CACHE_ALIAS]
        SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
        prefix = SessionStore().cache_key_prefix
        
        try:
            cached_entries = []
            user_ids = set()
            for key in cache.iter_keys(f"{prefix}*"):
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                
                session_key = key.replace(prefix, "")
                session_store = SessionStore(session_key=session_key)
                if session_store.is_empty():
                    continue
                    
                data = session_store.load()
                user_id = data.get("_auth_user_id")
                if not user_id:
                    continue
                
                user_ids.add(user_id)
                
                # Approximate expire date based on Redis TTL
                try:
                    ttl = cache.ttl(key)
                    expire_date = now + timezone.timedelta(seconds=ttl) if ttl else now
                except Exception:
                    expire_date = now + timezone.timedelta(seconds=settings.SESSION_COOKIE_AGE)
                    
                cached_entries.append((session_key, data, str(user_id), expire_date))

            users_by_id = {str(u.id): u for u in User.objects.filter(id__in=user_ids)}

            for session_key, data, user_id, expire_date in cached_entries:
                user = users_by_id.get(user_id)
                if not user:
                    continue

                sessions_data.append(
                    {
                        "session_key": session_key,
                        "user": user,
                        "last_login": user.last_login,
                        "expire_date": expire_date,
                        "is_current": session_key_to_is_current.get(session_key, False),
                        "ip_address": data.get("ip_address"),
                        "user_agent": data.get("user_agent"),
                        "last_activity": data.get("last_activity"),
                    }
                )
            active_count = len(sessions_data)
        except Exception as e:
            logger.error(f"Error fetching cache sessions: {e}")

    # Sort by user then expire_date desc
    sessions_data.sort(
        key=lambda s: (s["user"].full_name or "", -int(s["expire_date"].timestamp()) if s["expire_date"] else 0)
    )

    context = {
        "sessions": sessions_data,
        "active_count": active_count,
    }

    return render(request, "user/sessions.html", context)


@require_POST
def invalidate_all_sessions(request):
    """Invalidate all active sessions (logs everyone out)."""
    from django.conf import settings
    from importlib import import_module
    
    deleted = 0
    if settings.SESSION_ENGINE in ["django.contrib.sessions.backends.db", "django.contrib.sessions.backends.cached_db"]:
        now = timezone.now()
        qs = Session.objects.filter(expire_date__gt=now)
        deleted = qs.count()
        qs.delete()
    elif settings.SESSION_ENGINE == "django.contrib.sessions.backends.cache":
        from django.core.cache import caches
        cache = caches[settings.SESSION_CACHE_ALIAS]
        SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
        prefix = SessionStore().cache_key_prefix
        
        try:
            keys_to_delete = []
            for key in cache.iter_keys(f"{prefix}*"):
                keys_to_delete.append(key)
            
            if keys_to_delete:
                cache.delete_many(keys_to_delete)
                deleted = len(keys_to_delete)
        except Exception as e:
            logger.error(f"Error invalidating cache sessions: {e}")
            
    messages.success(request, f"Invalidated {deleted} active session(s).")
    return redirect("user:sessions")


@require_POST
def invalidate_session(request, session_key):
    """Invalidate a specific session by key."""
    from django.conf import settings
    from importlib import import_module
    SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
    
    try:
        session_store = SessionStore(session_key=session_key)
        session_store.delete()
        
        # Also try to delete from DB if it exists (for robustness)
        if settings.SESSION_ENGINE in ["django.contrib.sessions.backends.db", "django.contrib.sessions.backends.cached_db"]:
            Session.objects.filter(session_key=session_key).delete()
            
        messages.success(request, "Session invalidated.")
    except Exception as e:
        logger.error(f"Error invalidating session {session_key}: {e}")
        messages.error(request, "Session not found or error invalidating.")
        
    return redirect("user:sessions")


@required_permission("user.change_customuser")
def reset_user_password(request, user_id):
    """Reset password for a specific user."""
    user = get_object_or_404(User, id=user_id)

    if request.method == "POST":
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data["new_password"]
            user.set_password(new_password)
            user.save()
            messages.success(
                request, f"Password reset successfully for {user.full_name}!"
            )
            return redirect("user:detail", pk=user_id)
    else:
        form = PasswordResetForm()

    context = {
        "form": form,
        "user": user,
        "title": f"Reset Password - {user.full_name}",
    }

    return render(request, "user/reset_password.html", context)


# ==================== SALARY CRUD ====================


@required_permission("user.add_salary")
def salary_create(request, user_id):
    """Create a new salary record for a user."""
    user = get_object_or_404(User, id=user_id)

    if request.method == "POST":
        form = SalaryForm(request.POST, user=user)
        if form.is_valid():
            salary = form.save(commit=False)
            salary.user = user
            salary.created_by = request.user
            # If effective_to is set, end the current salary
            if salary.effective_to:
                current_salary = user.salaries.filter(effective_to__isnull=True).first()
                if current_salary:
                    current_salary.effective_to = salary.effective_from
                    current_salary.save()
            salary.save()
            messages.success(request, "Salary record created successfully!")
            return redirect("user:detail", pk=user_id)
    else:
        form = SalaryForm(user=user)

    context = {
        "form": form,
        "user": user,
        "title": f"Create Salary - {user.full_name}",
    }
    return render(request, "user/salary/form.html", context)


@required_permission("user.change_salary")
def salary_edit(request, user_id, salary_id):
    """Edit an existing salary record."""
    user = get_object_or_404(User, id=user_id)
    salary = get_object_or_404(Salary, id=salary_id, user=user)

    if request.method == "POST":
        form = SalaryForm(request.POST, instance=salary, user=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Salary record updated successfully!")
            return redirect("user:detail", pk=user_id)
    else:
        form = SalaryForm(instance=salary, user=user)

    context = {
        "form": form,
        "user": user,
        "salary": salary,
        "title": f"Edit Salary - {user.full_name}",
    }
    return render(request, "user/salary/form.html", context)


@required_permission("user.delete_salary")
def salary_delete(request, user_id, salary_id):
    """Delete a salary record."""
    user = get_object_or_404(User, id=user_id)
    salary = get_object_or_404(Salary, id=salary_id, user=user)

    if request.method == "POST":
        salary.delete()
        messages.success(request, "Salary record deleted successfully!")
        return redirect("user:detail", pk=user_id)

    context = {"user": user, "salary": salary}
    return render(request, "user/salary/delete.html", context)


# ==================== TRANSACTION CRUD ====================


@required_permission("user.add_transaction")
def transaction_create(request, user_id):
    """Create a new transaction for a user."""
    user = get_object_or_404(User, id=user_id)

    if request.method == "POST":
        form = TransactionForm(request.POST, user=user)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.user = user
            transaction.created_by = request.user
            transaction.save()
            messages.success(request, "Transaction created successfully!")
            return redirect("user:detail", pk=user_id)
    else:
        form = TransactionForm(user=user)

    context = {
        "form": form,
        "user": user,
        "title": f"Create Transaction - {user.full_name}",
    }
    return render(request, "user/transaction/form.html", context)


@required_permission("user.change_transaction")
def transaction_edit(request, user_id, transaction_id):
    """Edit an existing transaction."""
    user = get_object_or_404(User, id=user_id)
    transaction = get_object_or_404(Transaction, id=transaction_id, user=user)

    if request.method == "POST":
        form = TransactionForm(request.POST, instance=transaction, user=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Transaction updated successfully!")
            return redirect("user:detail", pk=user_id)
    else:
        form = TransactionForm(instance=transaction, user=user)

    context = {
        "form": form,
        "user": user,
        "transaction": transaction,
        "title": f"Edit Transaction - {user.full_name}",
    }
    return render(request, "user/transaction/form.html", context)


@required_permission("user.delete_transaction")
def transaction_delete(request, user_id, transaction_id):
    """Delete a transaction."""
    user = get_object_or_404(User, id=user_id)
    transaction = get_object_or_404(Transaction, id=transaction_id, user=user)

    if request.method == "POST":
        transaction.delete()
        messages.success(request, "Transaction deleted successfully!")
        return redirect("user:detail", pk=user_id)

    context = {"user": user, "transaction": transaction}
    return render(request, "user/transaction/delete.html", context)


# ==================== COMMISSION VIEWS ====================


def user_commission(request, user_id):
    """View commission data for a user by month and year."""
    user = get_object_or_404(User, id=user_id)
    current_salary = user.current_salary
    is_commission_active = bool(user.is_active and user.is_commission_eligible)

    context = {
        "user": user,
        "current_salary": current_salary,
        "is_commission_active": is_commission_active,
    }

    return render(request, "user/commission/home.html", context)


def fetch_user_commission(request, user_id):
    """AJAX: fetch commission data for a user with pagination and optional sorting."""
    user = get_object_or_404(User, id=user_id)

    # Get date range using getDates utility (now accepts date_range and start_date/end_date directly)
    start_datetime, end_datetime = getDates(request)

    # Get invoices created by this user and filter by date range
    invoices = Invoice.objects.filter(sold_by=user).filter(
        invoice_date__gte=start_datetime, invoice_date__lte=end_datetime
    )

    valid_sort_fields = {
        "invoice_date": "invoice__invoice_date",
        "-invoice_date": "-invoice__invoice_date",
        "commission_amount": "commission_percentage",  # Approximate sort
        "-commission_amount": "-commission_percentage",
    }

    valid_sorts = table_sorting(request, valid_sort_fields, "-invoice__invoice_date")

    invoice_items = (
        InvoiceItem.objects.filter(invoice__in=invoices, commission_percentage__gt=0)
        .select_related("invoice", "product_variant__product")
        .order_by(*valid_sorts)
    )

    return render_paginated_response(
        request,
        invoice_items,
        "user/commission/fetch.html",
        per_page=20,
    )


def fetch_commission_summary(request, user_id):
    """AJAX: fetch commission summary data (totals and monthly summary)."""
    user = get_object_or_404(User, id=user_id)
    start_datetime, end_datetime = getDates(request)
    summary = CommissionService.get_user_commission_summary(user, start_datetime, end_datetime)
    summary["success"] = True
    return JsonResponse(summary)


# ==================== DASHBOARD VIEWS ====================


@required_permission("user.view_dashboard")
def user_dashboard(request):
    """Render the user dashboard page (all data loaded via AJAX)."""
    return render(request, "user/dashboard.html")


@required_permission("user.view_dashboard")
def user_dashboard_fetch(request):
    """AJAX endpoint: return all-user sales and commission dashboard data."""
    start_date, end_date = getDates(request)

    invoices = Invoice.objects.filter(
        invoice_date__gte=start_date,
        invoice_date__lte=end_date,
        is_cancelled=False,
    )

    items = InvoiceItem.objects.filter(
        invoice__in=invoices,
        commission_percentage__gt=0,
    ).select_related("invoice__sold_by")

    user_data = defaultdict(
        lambda: {
            "total_sales": Decimal("0"),
            "total_commission": Decimal("0"),
            "invoices": set(),
            "item_count": 0,
            "user_name": "",
            "user_id": None,
        }
    )

    for item in items:
        user = item.invoice.sold_by
        key = user.id
        user_data[key]["total_sales"] += item.discounted_amount
        user_data[key]["total_commission"] += item.commission_amount
        user_data[key]["invoices"].add(item.invoice_id)
        user_data[key]["item_count"] += 1
        user_data[key]["user_name"] = str(user)
        user_data[key]["user_id"] = user.id

    users_breakdown = []
    for uid, data in user_data.items():
        rate = (
            (data["total_commission"] / data["total_sales"] * 100)
            if data["total_sales"] > 0
            else 0
        )
        users_breakdown.append(
            {
                "user_id": data["user_id"],
                "user_name": data["user_name"],
                "total_sales": round(float(data["total_sales"]), 2),
                "total_commission": round(float(data["total_commission"]), 2),
                "commission_rate": round(float(rate), 1),
                "invoice_count": len(data["invoices"]),
                "item_count": data["item_count"],
            }
        )

    users_breakdown.sort(key=lambda x: x["total_sales"], reverse=True)

    total_sales_all = sum(u["total_sales"] for u in users_breakdown)
    total_commission_all = sum(u["total_commission"] for u in users_breakdown)
    avg_rate = (
        round(float(total_commission_all / total_sales_all * 100), 1)
        if total_sales_all > 0
        else 0
    )

    for u in users_breakdown:
        u["percentage"] = (
            round(u["total_sales"] / total_sales_all * 100, 1)
            if total_sales_all > 0
            else 0
        )
        u["commission_percentage"] = (
            round(u["total_commission"] / total_commission_all * 100, 1)
            if total_commission_all > 0
            else 0
        )

    return JsonResponse(
        {
            "success": True,
            "stats": {
                "total_sales": round(total_sales_all, 2),
                "total_commission": round(total_commission_all, 2),
                "users_with_sales": len(users_breakdown),
                "avg_commission_rate": avg_rate,
            },
            "users_breakdown": users_breakdown,
            "date_range": {
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
            },
        }
    )
