from django.apps import AppConfig


class ProvidersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "providers"

    def ready(self) -> None:
        from engine import integrations

        from . import checks, services  # noqa: F401 - registers the legacy database check

        integrations.register(
            services.integration_key,
            services.integration_configured,
            services.integration_settings,
        )
