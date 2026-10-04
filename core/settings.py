"""Django settings for OceanClouds ERP. Values come from .env (see DEPLOYMENT.md)."""
from pathlib import Path

import environ

# ------------------------------------------------------------------------------
# Paths & env
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_SECRET_KEY=(str, "change-me"),
    DJANGO_ALLOWED_HOSTS=(list, []),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
    DJANGO_SECURE_SSL_REDIRECT=(bool, False),
    DJANGO_SESSION_COOKIE_SECURE=(bool, False),
    DJANGO_CSRF_COOKIE_SECURE=(bool, False),
    DB_ENGINE=(str, "sqlite"),
    DB_NAME=(str, "db.sqlite3"),
    DB_USER=(str, ""),
    DB_PASSWORD=(str, ""),
    DB_HOST=(str, ""),
    DB_PORT=(str, ""),
    DB_CONN_MAX_AGE=(int, 60),
    APP_VERSION=(str, "dev"),
    REDIS_URL=(str, ""),
    LOGIN_IDLE_TIMEOUT_MINUTES=(int, 30),
    AWS_REGION=(str, ""),
    AWS_SES_SENDER=(str, ""),
    AWS_ACCESS_KEY_ID=(str, ""),
    AWS_SECRET_ACCESS_KEY=(str, ""),
    AWS_S3_ENABLED=(bool, False),
    AWS_STORAGE_BUCKET_NAME=(str, ""),
    AWS_S3_REGION_NAME=(str, "ap-south-1"),
    EMAIL_SENDING_ENABLED=(bool, True),
    EMAIL_DEFAULT_FROM=(str, ""),
    EMAIL_DEFAULT_REPLY_TO=(str, ""),

    WHATSAPP_SENDING_ENABLED=(bool, False),
    WHATSAPP_PROVIDER=(str, "meta"),  # meta or msg91

    META_WHATSAPP_ACCESS_TOKEN=(str, ""),
    META_WHATSAPP_PHONE_NUMBER_ID=(str, ""),
    META_WHATSAPP_BUSINESS_ACCOUNT_ID=(str, ""),
    META_WHATSAPP_API_VERSION=(str, "v22.0"),

    MSG91_AUTHKEY=(str, ""),
    MSG91_WHATSAPP_NAMESPACE=(str, ""),
    MSG91_WHATSAPP_INTEGRATED_NUMBER=(str, ""),
)
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env("DJANGO_DEBUG")
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT")
SESSION_COOKIE_SECURE = env.bool("DJANGO_SESSION_COOKIE_SECURE")
CSRF_COOKIE_SECURE = env.bool("DJANGO_CSRF_COOKIE_SECURE")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
APP_VERSION = env("APP_VERSION")
AWS_REGION = env("AWS_REGION")
AWS_SES_SENDER = env("AWS_SES_SENDER")
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
AWS_S3_ENABLED = env.bool("AWS_S3_ENABLED")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME")
EMAIL_SENDING_ENABLED = env.bool("EMAIL_SENDING_ENABLED")
EMAIL_DEFAULT_FROM = env("EMAIL_DEFAULT_FROM") or AWS_SES_SENDER
EMAIL_DEFAULT_REPLY_TO = env("EMAIL_DEFAULT_REPLY_TO") or AWS_SES_SENDER
WHATSAPP_SENDING_ENABLED = env.bool("WHATSAPP_SENDING_ENABLED")
WHATSAPP_PROVIDER = env("WHATSAPP_PROVIDER")

META_WHATSAPP_ACCESS_TOKEN = env("META_WHATSAPP_ACCESS_TOKEN")
META_WHATSAPP_PHONE_NUMBER_ID = env("META_WHATSAPP_PHONE_NUMBER_ID")
META_WHATSAPP_BUSINESS_ACCOUNT_ID = env("META_WHATSAPP_BUSINESS_ACCOUNT_ID")
META_WHATSAPP_API_VERSION = env("META_WHATSAPP_API_VERSION")

MSG91_AUTHKEY = env("MSG91_AUTHKEY")
MSG91_WHATSAPP_NAMESPACE = env("MSG91_WHATSAPP_NAMESPACE")
MSG91_WHATSAPP_INTEGRATED_NUMBER = env("MSG91_WHATSAPP_INTEGRATED_NUMBER")

# ------------------------------------------------------------------------------
# Apps
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "channels",
    "django_crontab",
    "storages",
]


LOCAL_APPS = [
    "common.apps.CommonConfig",
    "crm.apps.CrmConfig",
    "sales.apps.SalesConfig",
    "adminpanel",
    "events",
    "services.apps.ServicesConfig",
    "messaging.apps.MessagingConfig",
    "projects.apps.ProjectsConfig",
    "reports",
    "todos.apps.TodosConfig",
    "ui",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ------------------------------------------------------------------------------
# Middleware / URLConf / WSGI
# ------------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "common.middleware.CloseExpiredLoginSessionsMiddleware",
    "common.middleware.RequireNoticeAcknowledgementMiddleware",
    "common.middleware.ClearFrontendMessagesBeforeAdminMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"
WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

# ------------------------------------------------------------------------------
# Live updates (Django Channels)
# ------------------------------------------------------------------------------
# Redis carries websocket pushes between Gunicorn/Uvicorn workers. Without
# REDIS_URL (local runserver, tests) an in-process layer is used instead.
REDIS_URL = env("REDIS_URL")

if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                # redis-py 8 defaults to a 5 s socket timeout, the same as
                # channels_redis' 5 s blocking pop, which kills idle sockets.
                "hosts": [{"address": REDIS_URL, "socket_timeout": 15}],
                "capacity": 200,
                "expiry": 30,
            },
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }

# ------------------------------------------------------------------------------
# Templates (global templates live in ui/templates)
# ------------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "ui" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "common.context_processors.notifications",
                "django.contrib.messages.context_processors.messages",
                "ui.context_processors.app_version",
                "ui.context_processors.navigation",
            ],
        },
    },
]

# ------------------------------------------------------------------------------
# Database (SQLite by default; Postgres via .env)
# ------------------------------------------------------------------------------
DB_ENGINE = env("DB_ENGINE")

if DB_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "HOST": env("DB_HOST"),
            "PORT": env("DB_PORT"),
            "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE"),
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    # sqlite fallback
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / env("DB_NAME"),
        }
    }

# ------------------------------------------------------------------------------
# Auth / i18n / tz
# ------------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------------------
# Static & Media
# ------------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "ui" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files live under media/ locally. Individual FileField/ImageField
# upload_to values create their own subfolders inside this directory.
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

# MEDIA: local by default, S3 in production if enabled
if AWS_S3_ENABLED:
    # Django 5.1+ ignores DEFAULT_FILE_STORAGE; storage is set via STORAGES.
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False

    # Uploads include signed contracts, so links are signed and expire
    # rather than relying on a public bucket.
    AWS_QUERYSTRING_AUTH = True

    MEDIA_URL = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/"


# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "null": {"class": "logging.NullHandler"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        # Without this, 500 errors leave no traceback in the container logs
        # when DEBUG is off.
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "fontTools": {"handlers": ["null"], "level": "ERROR", "propagate": False},
        "weasyprint": {"handlers": ["null"], "level": "ERROR", "propagate": False},
    },
}


# ------------------------------------------------------------------------------
# Default primary key type
# ------------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "ui:login"

# ------------------------------------------------------------------------------
# Cron jobs (django-crontab)
# ------------------------------------------------------------------------------
# Only takes effect after `manage.py crontab add` on a host with cron; the
# Docker setup has no cron, so this does not run there.
CRONJOBS = [
    ("0 0 * * *", "django.core.management.call_command", ["generate_due_todos"]),
]

# Authentication has a fixed maximum lifetime from the moment of login. A
# login still open at the limit is closed with a missing logout, which the
# user corrects through a request their project manager approves.
LOGIN_SESSION_MAX_SECONDS = 12 * 60 * 60

# A day counts as attended once the day's login time adds up to this much.
ATTENDANCE_REQUIRED_SECONDS = 7 * 60 * 60
SESSION_COOKIE_AGE = LOGIN_SESSION_MAX_SECONDS
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = False

# A login with no user activity (clicks, typing, scrolling, page navigation)
# for this long is signed out, and its logout time is the last activity time.
# 0 turns idle logout off; the fixed deadline above always applies.
LOGIN_IDLE_TIMEOUT_SECONDS = env.int("LOGIN_IDLE_TIMEOUT_MINUTES") * 60

# Heartbeats are sent only while someone interacts with an open page.
BROWSER_HEARTBEAT_INTERVAL_SECONDS = 60
BROWSER_OFFLINE_THRESHOLD_SECONDS = 180
