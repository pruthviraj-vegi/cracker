from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'security'

    def ready(self):
        try:
            from . import signals  # noqa: F401
        except Exception:
            pass
