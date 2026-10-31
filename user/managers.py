"""
Custom user manager for the user app.
"""

from django.contrib.auth.models import BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.translation import gettext_lazy as _

from base.manager import SoftDeleteManager


class CustomUserManager(SoftDeleteManager, BaseUserManager):
    """Manager for CustomUser model, providing custom user creation methods."""

    def email_validator(self, email):
        """Validate the given email address."""
        try:
            validate_email(email)
        except ValidationError as exc:
            raise ValueError(_("Please provide a valid email address")) from exc

    def create_user(
        self,
        first_name,
        phone_number,
        password,
        last_name=None,
        email=None,
        **extra_fields
    ):
        """Create and save a regular User with the given details."""
        if not first_name:
            raise ValueError(_("Users must submit a first name"))
        if not phone_number:
            raise ValueError(_("Users must submit a phone number"))

        if email:
            email = self.normalize_email(email)
            self.email_validator(email)

        user = self.model(
            first_name=first_name,
            last_name=last_name or "",
            phone_number=phone_number,
            email=email,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        first_name,
        phone_number,
        password,
        last_name=None,
        email=None,
        **extra_fields
    ):
        """Create and save a SuperUser with the given details."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superusers must have is_staff=True"))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superusers must have is_superuser=True"))

        return self.create_user(
            first_name=first_name,
            phone_number=phone_number,
            password=password,
            last_name=last_name,
            email=email,
            **extra_fields
        )
