"""API Token Admin Configuration."""

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import APIToken, APIRequestLog


@admin.register(APIToken)
class APITokenAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "prefix_display",
        "purpose_truncated",
        "status_display",
        "allowed_ips_display",
        "expires_at",
        "last_used_info",
        "created_by",
        "created_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "purpose", "prefix")
    readonly_fields = (
        "token_hash",
        "prefix",
        "last_used_at",
        "last_used_ip",
        "created_at",
    )
    list_per_page = 25
    ordering = ("-created_at",)
    autocomplete_fields = ("created_by", "revoked_by")

    fieldsets = (
        (None, {"fields": ("name", "purpose")}),
        ("Token Details", {"fields": ("prefix", "token_hash"), "classes": ("collapse",)}),
        (
            "Access Control",
            {"fields": ("allowed_ips", "expires_at", "is_active")},
        ),
        (
            "Revocation",
            {
                "fields": ("revoked_at", "revoked_by"),
                "classes": ("collapse",),
            },
        ),
        (
            "Usage",
            {
                "fields": ("last_used_at", "last_used_ip"),
                "classes": ("collapse",),
            },
        ),
        ("System", {"fields": ("created_by", "created_at"), "classes": ("collapse",)}),
    )

    actions = ["revoke_tokens", "activate_tokens"]

    def prefix_display(self, obj):
        return format_html("<code>{}</code>", obj.prefix)

    prefix_display.short_description = "Prefix"

    def purpose_truncated(self, obj):
        if obj.purpose and len(obj.purpose) > 40:
            return obj.purpose[:40] + "..."
        return obj.purpose or "—"

    purpose_truncated.short_description = "Purpose"

    def status_display(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="color: green; font-weight: bold;">Active</span>'
            )
        return format_html(
            '<span style="color: red; font-weight: bold;">Revoked</span>'
        )

    status_display.short_description = "Status"

    def allowed_ips_display(self, obj):
        if not obj.allowed_ips:
            return format_html('<span style="color: gray;">Any</span>')
        return ", ".join(obj.allowed_ips)

    allowed_ips_display.short_description = "Allowed IPs"

    def last_used_info(self, obj):
        if obj.last_used_at:
            return format_html("{}<br><small>{}</small>", obj.last_used_at.strftime("%Y-%m-%d %H:%M"), obj.last_used_ip or "")
        return "Never"

    last_used_info.short_description = "Last Used"

    def revoke_tokens(self, request, queryset):
        now = timezone.now()
        updated = queryset.filter(is_active=True).update(
            is_active=False, revoked_at=now, revoked_by=request.user
        )
        self.message_user(request, f"Revoked {updated} token(s).", level="SUCCESS")

    revoke_tokens.short_description = "Revoke selected tokens"

    def activate_tokens(self, request, queryset):
        updated = queryset.filter(is_active=False).update(
            is_active=True, revoked_at=None, revoked_by=None
        )
        self.message_user(request, f"Activated {updated} token(s).", level="SUCCESS")

    activate_tokens.short_description = "Activate selected tokens"


@admin.register(APIRequestLog)
class APIRequestLogAdmin(admin.ModelAdmin):
    list_display = (
        "endpoint",
        "method_display",
        "response_status_display",
        "ip_address",
        "token_display",
        "response_time_display",
        "requested_at",
    )
    list_filter = ("method", "response_status", "requested_at")
    search_fields = ("endpoint", "ip_address", "token__name")
    readonly_fields = (
        "token",
        "endpoint",
        "method",
        "ip_address",
        "response_status",
        "response_time_ms",
        "requested_at",
    )
    list_per_page = 50
    ordering = ("-requested_at",)
    date_hierarchy = "requested_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def method_display(self, obj):
        color = {"GET": "#61affe", "POST": "#49cc90", "PUT": "#fca130", "DELETE": "#f93e3e"}.get(obj.method, "#999")
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.method)

    method_display.short_description = "Method"

    def response_status_display(self, obj):
        if 200 <= obj.response_status < 300:
            color = "green"
        elif 400 <= obj.response_status < 500:
            color = "orange"
        else:
            color = "red"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.response_status,
        )

    response_status_display.short_description = "Status"

    def token_display(self, obj):
        if obj.token:
            return format_html("<code>{}</code>", obj.token.prefix)
        return "—"

    token_display.short_description = "Token"

    def response_time_display(self, obj):
        if obj.response_time_ms is not None:
            return f"{obj.response_time_ms}ms"
        return "—"

    response_time_display.short_description = "Response Time"
