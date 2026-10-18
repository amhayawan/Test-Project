"""Settings for the HAZ integrated management system (v2).

Everything environment-specific comes from environment variables, so the same code runs
on a developer PC, the office and the Egypt-hosted cloud server:

  HAZ_SECRET_KEY        required in production
  HAZ_DEBUG             "1" only on a developer PC
  HAZ_DATABASE_URL      e.g. postgresql://user:pass@host:5432/haz  (default: local SQLite file)
  HAZ_ALLOWED_HOSTS     comma separated, e.g. erp.haz-association.org
  HAZ_DATA_DIR          folder for the local database and uploaded files
  HAZ_HTTPS             "1" when served behind HTTPS (secure cookies, HSTS)
"""
import os
from pathlib import Path

import dj_database_url
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("HAZ_DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEBUG = os.environ.get("HAZ_DEBUG") == "1"
SECRET_KEY = os.environ.get("HAZ_SECRET_KEY")
if not SECRET_KEY:  # desktop / office installs: generate once and keep it in the data folder
    key_file = DATA_DIR / "secret.key"
    if not key_file.exists():
        import secrets
        key_file.write_text(secrets.token_urlsafe(50))
    SECRET_KEY = key_file.read_text().strip()

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("HAZ_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "core",
    "approvals",
    "crm",
    "cases",
    "dashboards",
    "hr",
    "finance",
    "supply",
    "projects",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "accounts.middleware.UserLanguageMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.FirstRunMiddleware",
    "core.middleware.RequestContextMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "haz.urls"
WSGI_APPLICATION = "haz.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "django.template.context_processors.i18n",
        "core.context.navigation",
    ]},
}]

DATABASES = {"default": dj_database_url.parse(
    os.environ.get("HAZ_DATABASE_URL") or f"sqlite:///{DATA_DIR / 'haz.db'}", conn_max_age=60)}
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = 20

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
    "core.hashers.WerkzeugImportedHasher",   # passwords carried over from v1 ("wz$...")
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Accounts lock for LOCKOUT_MINUTES after MAX_FAILED_LOGINS wrong passwords.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

SESSION_COOKIE_AGE = int(os.environ.get("HAZ_SESSION_MINUTES", "30")) * 60
SESSION_SAVE_EVERY_REQUEST = True          # idle timeout, not absolute
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
if os.environ.get("HAZ_HTTPS") == "1":
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 31536000
    CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS]

LANGUAGE_CODE = "ar"
LANGUAGES = [("ar", _("Arabic")), ("en", _("English"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Africa/Cairo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = DATA_DIR / "staticfiles"
SERVE_STATIC = DEBUG or os.environ.get("HAZ_SERVE_STATIC") == "1"
MEDIA_ROOT = DATA_DIR / "media"
MAX_UPLOAD_MB = 10

# Weekly rest days for counting leave (Python weekday numbers: Monday=0 ... Friday=4, Saturday=5).
WEEKEND_DAYS = tuple(int(d) for d in os.environ.get("HAZ_WEEKEND_DAYS", "4,5").split(",") if d.strip())
DATA_UPLOAD_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_MEMORY_SIZE = (MAX_UPLOAD_MB + 2) * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CURRENCY = "EGP"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
