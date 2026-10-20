"""Only the fixed foundation queue is enabled in T04."""
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
app = Celery("axiom")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
