import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DEBUG", "false").lower() in {"1", "true", "yes"}
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-not-for-production"
    else:
        raise ImproperlyConfigured("SECRET_KEY is required in production.")


def _csv(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def _host(value):
    return value.replace("https://", "").replace("http://", "").split("/")[0].strip()


ALLOWED_HOSTS = _csv("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = _csv(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000",
)

railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
if railway_domain:
    host = _host(railway_domain)
    if host and host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)
    origin = f"https://{host}"
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)

if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"):
    for host in (".up.railway.app", ".railway.app"):
        if host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(host)
    for origin in ("https://*.up.railway.app", "https://*.railway.app"):
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)

if DEBUG:
    ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "axes",
    "accounts",
    "notes",
    "core",
    "ramble_mcp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.TrafficMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.WebErrorLoggingMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

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
                "accounts.context_processors.minute_usage",
                "core.context_processors.nav_page",
                "notes.context_processors.app_shell",
            ],
        },
    }
]

DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "notes:list"
LOGOUT_REDIRECT_URL = "notes:home"

_RESERVED_ADMIN_URLS = {
    "login",
    "register",
    "signup",
    "logout",
    "settings",
    "kpi",
    "api",
    "mcp",
    "healthz",
    "roll",
    "library",
    "albums",
    "notes",
    "privacy",
    "terms",
    "support",
}


def _admin_url():
    raw = os.environ.get("ADMIN_URL", "").strip().strip("/")
    if not raw:
        if DEBUG:
            return "admin"
        raise ImproperlyConfigured("ADMIN_URL is required in production.")
    first = raw.split("/")[0]
    # Path segment(s) only — reject hosts/URLs like "yourramble.com/admin".
    if "://" in raw or "." in first or first.lower() == "localhost":
        raise ImproperlyConfigured(
            "ADMIN_URL must be a path (e.g. 'admin' or 'secret-panel'), not a URL or hostname."
        )
    if first in _RESERVED_ADMIN_URLS:
        raise ImproperlyConfigured(f"ADMIN_URL cannot use the reserved path '{raw}'.")
    return raw


ADMIN_URL = _admin_url()
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_RESET_ON_SUCCESS = True
# Lock when either the username or the IP exceeds the failure limit.
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = True
AXES_LOCKOUT_CALLABLE = "accounts.lockout.axes_lockout_response"
AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")
IPWARE_ALGORITHM = "legacy"

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = _csv("CORS_ALLOWED_ORIGINS")
CORS_URLS_REGEX = r"^/(?!mcp(?:/|$)).*"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
# Model IDs are server-owned so they can change without an app release.
ASSEMBLYAI_BATCH_MODEL = (
    os.environ.get("ASSEMBLYAI_BATCH_MODEL", "universal-3-pro").strip() or "universal-3-pro"
)
ASSEMBLYAI_STREAMING_MODEL = (
    os.environ.get("ASSEMBLYAI_STREAMING_MODEL", "universal-streaming-english").strip()
    or "universal-streaming-english"
)
ASSEMBLYAI_LANGUAGE_CODE = os.environ.get("ASSEMBLYAI_LANGUAGE_CODE", "en_uk").strip() or "en_uk"
ASSEMBLYAI_STREAMING_SAMPLE_RATE = int(
    os.environ.get("ASSEMBLYAI_STREAMING_SAMPLE_RATE", "16000") or "16000"
)
ASSEMBLYAI_STREAM_TOKEN_TTL_SECONDS = int(
    os.environ.get("ASSEMBLYAI_STREAM_TOKEN_TTL_SECONDS", "60") or "60"
)
ASSEMBLYAI_STREAM_MAX_SESSION_SECONDS = int(
    os.environ.get("ASSEMBLYAI_STREAM_MAX_SESSION_SECONDS", "360") or "360"
)
OPENAI_TIDY_MODEL = os.environ.get("OPENAI_TIDY_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
# Price ID for £9.99/month GBP (required for embedded Checkout form).
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "").strip()
# Customer Portal configuration (bpc_…).
STRIPE_PORTAL_CONFIGURATION_ID = os.environ.get("STRIPE_PORTAL_CONFIGURATION_ID", "").strip()
APP_STORE_URL = os.environ.get(
    "APP_STORE_URL",
    "https://apps.apple.com/gb/app/ramble-talk-to-text-notes/id6810091886",
).strip()
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://yourramble.com").strip().rstrip("/")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    "Tom <hello@mail.yourramble.com>",
).strip()
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO", "tom@yourramble.com").strip()
# Tests can set True so take-ready webhook POSTs run inline after on_commit.
TAKE_READY_WEBHOOK_INLINE = os.environ.get("TAKE_READY_WEBHOOK_INLINE", "").lower() in {
    "1",
    "true",
    "yes",
}
DATA_UPLOAD_MAX_MEMORY_SIZE = 40 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 40 * 1024 * 1024

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://js.stripe.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://*.stripe.com; "
    "connect-src 'self' https://api.stripe.com https://*.stripe.com; "
    "frame-src https://js.stripe.com https://hooks.stripe.com https://*.stripe.com; "
    "media-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self' https://checkout.stripe.com https://billing.stripe.com https://hooks.stripe.com https://*.stripe.com; "
    "frame-ancestors 'none'"
)
PERMISSIONS_POLICY = (
    "accelerometer=(), "
    "autoplay=(), "
    "camera=(), "
    "display-capture=(), "
    "encrypted-media=(), "
    "fullscreen=(self), "
    "geolocation=(), "
    "gyroscope=(), "
    "magnetometer=(), "
    "microphone=(self), "
    "midi=(), "
    "payment=(self), "
    "picture-in-picture=(), "
    "publickey-credentials-get=(), "
    "screen-wake-lock=(), "
    "usb=(), "
    "web-share=(self), "
    "xr-spatial-tracking=(), "
    "clipboard-write=(self), "
    "interest-cohort=()"
)
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    CONTENT_SECURITY_POLICY += "; upgrade-insecure-requests"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "ramble": {
            "handlers": ["console"],
            "level": os.environ.get("RAMBLE_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
