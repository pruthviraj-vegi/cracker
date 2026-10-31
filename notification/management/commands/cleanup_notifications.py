"""Management command to clean up old notifications and PDF jobs."""

from django.core.management.base import BaseCommand

from notification.models import Notification
from report.models import PdfJob


class Command(BaseCommand):
    """Delete notifications and PDF jobs older than N days (default 30)."""

    help = "Delete old notifications and PDF jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Delete records older than this many days (default: 30).",
        )
        parser.add_argument(
            "--only",
            choices=["notifications", "pdfjobs"],
            default=None,
            help="Clean up only one type. Omit to clean both.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        target = options["only"]

        if target != "pdfjobs":
            count = Notification.cleanup_old(days=days)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {count} notification(s) older than {days} days."
                )
            )

        if target != "notifications":
            count = PdfJob.cleanup_old(days=days)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {count} PDF job(s) older than {days} days."
                )
            )
