"""Loopback development settings; secrets are supplied by the environment."""
import os

SECRET_KEY = os.environ["AXIOM_SECRET_KEY"]
if len(SECRET_KEY) < 50:
    raise ValueError("AXIOM_SECRET_KEY must contain at least 50 characters")
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "web", "testserver"]
INSTALLED_APPS = ["foundation", "runtime"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "HOST": os.environ["AXIOM_DB_HOST"],
    "PORT": "5432",
    "NAME": os.environ["AXIOM_DB_NAME"],
    "USER": os.environ["AXIOM_DB_USER"],
    "PASSWORD": os.environ["AXIOM_DB_PASSWORD"],
    "OPTIONS": {"connect_timeout": 3},
}}
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REDIS_URL = os.environ["AXIOM_REDIS_URL"]
CELERY_BROKER_URL = REDIS_URL
CELERY_TASK_DEFAULT_QUEUE = "foundation"
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_TIMEOUT = 3
CELERY_BROKER_TRANSPORT_OPTIONS = {"socket_timeout": 3, "socket_connect_timeout": 3}
