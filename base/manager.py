"""
Module containing a reusable softly-deleting Model manager and an abstract model
for implementing soft delete functionality across the project.
"""

from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator


class SoftDeleteManager(models.Manager):
    """
    Custom manager for SoftDeleteModel.

    This manager overrides the default queryset to automatically
    exclude any objects that have been soft-deleted.
    """

    def get_queryset(self):
        """Return a queryset that filters out soft-deleted items."""
        # By default, only return objects that are not deleted.
        return super().get_queryset().filter(is_deleted=False)

    def all_objects(self):
        """Return a queryset encompassing ALL objects, including soft-deleted ones."""
        # Use this method to get ALL objects, including soft-deleted ones.
        return super().get_queryset()

    def deleted_objects(self):
        """Return a queryset of ONLY soft-deleted objects."""
        # Use this method to get ONLY soft-deleted objects.
        return super().get_queryset().filter(is_deleted=True)

    def hard_delete(self):
        """Permanently delete objects matching the current queryset filters."""
        return self.all_objects().filter(
            pk__in=self.values_list("pk", flat=True)
        ).delete()


class SoftDeleteModel(models.Model):
    """
    An abstract base class model that provides soft delete functionality.

    Any model that inherits from this will get the `is_deleted` and
    `deleted_at` fields, along with methods to soft delete and restore.
    """

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Use our custom manager
    objects = SoftDeleteManager()

    # Also keep the default manager handy if you need it for some reason.
    all_objects = models.Manager()

    def soft_delete(self):
        """Marks the object as deleted."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save()

    def restore(self):
        """Restores a soft-deleted object."""
        self.is_deleted = False
        self.deleted_at = None
        self.save()

    def delete(self, using=None, keep_parents=False):
        """
        Overrides the default delete() method to perform a soft delete.
        """
        self.soft_delete()

    class Meta:
        abstract = True  # This makes it an abstract model


# Phone number validator - 10 digits only, no plus symbol
phone_regex = RegexValidator(
    regex=r"^\d{10}$",
    message="Phone number must be exactly 10 digits (e.g., 9876543210).",
)
