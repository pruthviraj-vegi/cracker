"""
Admin configurations for the user app.
"""

import json

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Admin interface for CustomUser model."""

    # Define the fields to display in the list view
    list_display = (
        "first_name",
        "phone_number",
        "email",
        "is_active",
        "is_staff",
        "date_joined",
    )

    # Define the fields to display in the detail view
    fieldsets = (
        (None, {"fields": ("phone_number", "password")}),
        (_("Personal info"), {"fields": ("first_name", "email")}),
        (
            _("Role & Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            _("Important dates"),
            {"fields": ("last_login", "date_joined"), "classes": ("collapse",)},
        ),
    )

    # Define the fields to display when adding a new user
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "first_name",
                    "phone_number",
                    "email",
                    "groups",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    # Define search fields
    search_fields = ("first_name", "phone_number", "email")

    # Define filters
    list_filter = (
        "is_active",
        "is_staff",
        "is_superuser",
        "date_joined",
    )

    # Define ordering
    ordering = ("-date_joined",)

    # Define readonly fields
    readonly_fields = ("last_login", "date_joined")

    # Define actions
    actions = ["activate_users", "deactivate_users", "make_staff", "remove_staff"]

    # Custom actions
    def activate_users(self, request, queryset):
        """Activate selected users"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} user(s) were successfully activated.")

    activate_users.short_description = "Activate selected users"

    def deactivate_users(self, request, queryset):
        """Deactivate selected users"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} user(s) were successfully deactivated.")

    deactivate_users.short_description = "Deactivate selected users"

    def make_staff(self, request, queryset):
        """Make selected users staff"""
        updated = queryset.update(is_staff=True)
        self.message_user(request, f"{updated} user(s) were successfully made staff.")

    make_staff.short_description = "Make selected users staff"

    def remove_staff(self, request, queryset):
        """Remove staff status from selected users"""
        updated = queryset.update(is_staff=False)
        self.message_user(
            request, f"{updated} user(s) were successfully removed from staff."
        )

    remove_staff.short_description = "Remove staff status from selected users"

    # Override save method to ensure proper password hashing
    def save_model(self, request, obj, form, change):
        if not change:  # Creating new user
            obj.set_password(obj.password)
        elif "password" in form.changed_data:  # Password was changed
            obj.set_password(obj.password)
        super().save_model(request, obj, form, change)


# Customize admin site
admin.site.site_header = "Billing System Administration"
admin.site.site_title = "Billing Admin"
admin.site.index_title = "Welcome to Billing System Administration"


# Sessions admin: view active/expired sessions and invalidate selected ones
User = get_user_model()


class ActiveSessionFilter(admin.SimpleListFilter):
    """Filter sessions by active/expired status."""

    title = "Session status"
    parameter_name = "active"

    def lookups(self, request, model_admin):
        return (
            ("1", "Active"),
            ("0", "Expired"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        value = self.value()
        if value == "1":
            return queryset.filter(expire_date__gt=now)
        if value == "0":
            return queryset.filter(expire_date__lte=now)
        return queryset


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    """Admin interface for managing user sessions."""

    list_display = (
        "session_key_short",
        "user_display",
        "user_username",
        "user_last_login",
        "expire_date",
        "is_active_display",
    )
    list_filter = (ActiveSessionFilter, "expire_date")
    search_fields = ("session_key",)
    date_hierarchy = "expire_date"
    actions = ["invalidate_sessions"]
    readonly_fields = ("session_key", "expire_date", "session_data_pretty")
    fieldsets = (
        (None, {"fields": ("session_key", "expire_date", "session_data_pretty")}),
    )

    def session_key_short(self, obj):
        """Display a shortened version of the session key."""
        return (obj.session_key or "")[:8]

    session_key_short.short_description = "Session"

    def is_active_display(self, obj):
        """Check if the session is currently active."""
        return obj.expire_date > timezone.now()

    is_active_display.boolean = True
    is_active_display.short_description = "Active"

    def _get_user(self, obj):
        try:
            data = obj.get_decoded()
            user_id = data.get("_auth_user_id")
            if not user_id:
                return None
            return User.objects.filter(id=user_id).first()
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def user_display(self, obj):
        """Display the user's full name or username."""
        user = self._get_user(obj)
        if not user:
            return "-"
        return getattr(user, "first_name", None) or user.get_username()

    user_display.short_description = "User"

    def user_username(self, obj):
        """Display the user's username."""
        user = self._get_user(obj)
        return user.get_username() if user else "-"

    user_username.short_description = "Username"

    def user_last_login(self, obj):
        """Display the user's last login time."""
        user = self._get_user(obj)
        return user.last_login if user else None

    user_last_login.short_description = "Last login"

    def session_data_pretty(self, obj):
        """Display a pretty-printed version of the session data."""
        try:
            data = obj.get_decoded()
            return json.dumps(data, indent=2, sort_keys=True)
        except Exception:  # pylint: disable=broad-exception-caught
            return "<unreadable>"

    session_data_pretty.short_description = "Decoded data"

    def invalidate_sessions(self, request, queryset):
        """Invalidate selected sessions."""
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} session(s) invalidated.")

    invalidate_sessions.short_description = "Invalidate selected sessions"


