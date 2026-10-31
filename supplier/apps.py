from django.apps import AppConfig


class SupplierConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "supplier"

    def ready(self):
        import supplier.signals
