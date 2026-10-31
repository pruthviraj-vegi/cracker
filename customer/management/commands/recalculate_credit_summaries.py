from django.core.management.base import BaseCommand
from django.db import transaction
from customer.models import Customer, CustomerCreditSummary
import time


class Command(BaseCommand):
    help = "Recalculate credit summaries for all customers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--customer-id",
            type=int,
            help="Recalculate for specific customer",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Batch size for bulk updates",
        )

    def handle(self, *args, **options):
        customer_id = options.get("customer_id")
        batch_size = options.get("batch_size")

        if customer_id:
            self._recalculate_single(customer_id)
        else:
            self._recalculate_all(batch_size)

    def _recalculate_single(self, customer_id):
        try:
            customer = Customer.objects.get(id=customer_id)
            CustomerCreditSummary.recalculate_for_customer(customer)
            self.stdout.write(self.style.SUCCESS(f"✓ Recalculated for {customer.name}"))
        except Customer.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"✗ Customer {customer_id} not found"))

    def _recalculate_all(self, batch_size):
        customers = Customer.objects.all()
        total = customers.count()

        self.stdout.write(
            f"Recalculating {total} customers in batches of {batch_size}..."
        )

        start_time = time.time()
        processed = 0

        # Process in batches
        for i in range(0, total, batch_size):
            batch = customers[i : i + batch_size]

            with transaction.atomic():
                for customer in batch:
                    try:
                        CustomerCreditSummary.recalculate_for_customer(customer)
                        processed += 1
                    except Exception as e:
                        self.stdout.write(
                            self.style.WARNING(f"⚠ Failed for {customer.id}: {e}")
                        )

            self.stdout.write(f"Processed {processed}/{total}...")

        elapsed = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Successfully recalculated {processed} customers in {elapsed:.2f}s"
            )
        )
