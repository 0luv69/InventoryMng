from django.apps import AppConfig


class TransactionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.transactions'
    label = 'transactions'

    def ready(self):
        # Import signals so they are registered
        from . import signals
