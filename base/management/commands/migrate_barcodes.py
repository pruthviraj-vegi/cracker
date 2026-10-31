from django.core.management.base import BaseCommand
from django.db import transaction
from inventory.models import ProductVariant, BarcodeMapping
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "One-time migration: map old barcodes and generate new ones"

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Starting barcode migration..."))

        created_count = 0
        skipped_count = 0

        try:
            with transaction.atomic():
                variants = ProductVariant.objects.filter(is_deleted=False)

                mapped_variant_ids = set(
                    BarcodeMapping.objects.values_list("variant_id", flat=True)
                )

                barcode_mappings = []

                for variant in variants:
                    if variant.id in mapped_variant_ids:
                        skipped_count += 1
                        continue

                    old_barcode = variant.barcode

                    if not old_barcode:
                        variant.create_barcode()
                        variant.refresh_from_db()
                        old_barcode = variant.barcode

                    if not old_barcode:
                        self.stdout.write(
                            self.style.ERROR(
                                f"Variant {variant.id} has no barcode, skipping"
                            )
                        )
                        skipped_count += 1
                        continue

                    barcode_mappings.append(
                        BarcodeMapping(
                            barcode=old_barcode,
                            variant=variant,
                        )
                    )

                    # Generate NEW barcode (must save internally)
                    variant.create_barcode()

                if barcode_mappings:
                    BarcodeMapping.objects.bulk_create(barcode_mappings)
                    created_count = len(barcode_mappings)

        except Exception as e:
            logger.exception("Barcode migration failed")
            self.stderr.write(self.style.ERROR(str(e)))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Barcode migration completed. "
                f"Created: {created_count}, Skipped: {skipped_count}"
            )
        )
