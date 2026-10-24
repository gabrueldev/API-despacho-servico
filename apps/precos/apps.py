from django.apps import AppConfig


class PrecosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.precos"

    def ready(self) -> None:
        from . import signals  # noqa: F401
