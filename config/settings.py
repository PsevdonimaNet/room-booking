import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
# "web" - внутреннее имя сервиса в Docker-сети (Prometheus и k6 обращаются по нему)
if "web" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("web")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_prometheus",
    "rest_framework",
    "drf_spectacular",
    "core",
    "bookings",
    "web",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.RequestLogMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
    "core.middleware.DatabaseGuardMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "web.context.user_role",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("USE_SQLITE") == "1":
    # Запасной режим для локальной разработки без Docker/PostgreSQL.
    DATABASES = {
        "default": {
            "ENGINE": "django_prometheus.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django_prometheus.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "booking"),
            "USER": os.environ.get("POSTGRES_USER", "booking"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "booking"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
            # Быстрый отказ при недоступной БД вместо зависания запросов
            "OPTIONS": {"connect_timeout": 2, "options": "-c statement_timeout=10000"},
        }
    }

# Redis: кэш и сессии. Если REDIS_URL не задан - локальный кэш в памяти.
REDIS_URL = os.environ.get("REDIS_URL")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/rooms/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# Логирование: консоль + файл (логи действий пользователей и ошибок)
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "std"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "app.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
            "formatter": "std",
            "encoding": "utf-8",
        },
    },
    "root": {"handlers": ["console", "file"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}

# REST API
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "bookings.exceptions.api_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Room Booking API",
    "DESCRIPTION": "API бронирования переговорных комнат",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Правила бронирования
BOOKING_OPEN_HOUR = 8
BOOKING_CLOSE_HOUR = 20
BOOKING_MIN_HOURS = 1
BOOKING_MAX_HOURS = 4

# Работа за обратным прокси с HTTPS (Render, Cloudflare Tunnel)
CSRF_TRUSTED_ORIGINS = [
    origin for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin
]
if os.environ.get("DJANGO_BEHIND_PROXY") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
