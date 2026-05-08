from django.apps import AppConfig

class SmartInterviewAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smartInterviewApp'
    verbose_name = "Smart Interview Portal"  # This is the name that shows in the admin

    def ready(self):
        import smartInterviewApp.signals  # noqa: F401
