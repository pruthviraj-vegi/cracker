import uuid
import hashlib
import secrets

from django.conf import settings
from django.db import models

from base.utility import StringProcessor


class APIToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    purpose = models.TextField(blank=True)

    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    prefix = models.CharField(max_length=8, editable=False)

    allowed_ips = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="revoked_tokens",
    )

    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "API Token"
        verbose_name_plural = "API Tokens"

    def __str__(self):
        status = "Active" if self.is_active else "Revoked"
        return f"{self.name} ({status})"

    def clean(self):
        from django.core.exceptions import ValidationError
        import ipaddress

        super().clean()
        if not isinstance(self.allowed_ips, list):
            raise ValidationError({"allowed_ips": "Allowed IPs must be a list."})

        cleaned_ips = []
        for ip in self.allowed_ips:
            ip_str = str(ip).strip()
            if not ip_str:
                continue
            try:
                ipaddress.ip_address(ip_str)
                cleaned_ips.append(ip_str)
            except ValueError:
                raise ValidationError({"allowed_ips": f"'{ip_str}' is not a valid IP address."})
        self.allowed_ips = cleaned_ips

    def save(self, *args, **kwargs):
        self.name = StringProcessor(self.name).toTitle()
        self.purpose = StringProcessor(self.purpose).toTitle()
        super().save(*args, **kwargs)

    @classmethod
    def generate(cls, name, purpose, expires_at, created_by, allowed_ips=None):
        raw_token = secrets.token_hex(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        prefix = raw_token[:8]

        instance = cls.objects.create(
            name=name,
            purpose=purpose,
            token_hash=token_hash,
            prefix=prefix,
            allowed_ips=allowed_ips or [],
            expires_at=expires_at,
            created_by=created_by,
        )
        return instance, raw_token

    @classmethod
    def verify(cls, raw_token):
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        try:
            return cls.objects.get(token_hash=token_hash)
        except cls.DoesNotExist:
            return None


class APIRequestLog(models.Model):
    token = models.ForeignKey(
        APIToken,
        null=True,
        on_delete=models.SET_NULL,
        related_name="request_logs",
    )
    endpoint = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    ip_address = models.GenericIPAddressField()
    response_status = models.IntegerField()
    requested_at = models.DateTimeField(auto_now_add=True)
    response_time_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        verbose_name = "API Request Log"
        verbose_name_plural = "API Request Logs"

    def __str__(self):
        return f"{self.method} {self.endpoint} — {self.response_status} at {self.requested_at}"
