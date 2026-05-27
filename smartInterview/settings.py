import os
from pathlib import Path
from urllib.parse import urlparse


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_env_file(BASE_DIR / '.env')


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure--o3*fivnd_=lrfz$6(@9$bsiynr(hv1+!#fd+0o@3m*_7#nfj+'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = [
    'platform-app-wtf7jctfqq-uc.a.run.app',
    'shortlistii.com',
    '.shortlistii.com',
    '127.0.0.1',
    'localhost',
    'lvh.com',
    '.lvh.com',
    'lvh.me',
    '.lvh.me',
]


def _append_unique(values: list[str], candidate: str) -> None:
    item = (candidate or '').strip()
    if item and item not in values:
        values.append(item)


cloud_run_base_url = os.getenv('CLOUD_RUN_BASE_URL', '').strip()
cloud_run_host = urlparse(cloud_run_base_url).hostname or ''
if cloud_run_host:
    _append_unique(ALLOWED_HOSTS, cloud_run_host)

CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://lvh.com:8000",
    "http://litio.lvh.com:8000",
    "http://candidates.lvh.com:8000",
    "http://jobs.lvh.com:8000",
    "http://lvh.me:8000",
    "http://candidates.lvh.me:8000",
    "http://jobs.lvh.me:8000",
    "https://shortlistii.com",
    "https://www.shortlistii.com",
    "https://litio.shortlistii.com",
    "https://candidate.sshortlistii.com",
    "https://candidates.shortlistii.com",
    "https://jobs.shortlistii.com",
]
if cloud_run_base_url:
    _append_unique(CSRF_TRUSTED_ORIGINS, cloud_run_base_url)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'smartInterviewApp',
    'angular',
    'storages',
]

GS_BUCKET_NAME = os.getenv("GS_BUCKET_NAME", "")
GS_PROJECT_ID = os.getenv("GS_PROJECT_ID", "").strip() or None
GS_DEFAULT_ACL = None
GS_QUERYSTRING_AUTH = os.getenv("GS_QUERYSTRING_AUTH", "True").strip().lower() in {'1', 'true', 'yes', 'on'}
GS_FILE_OVERWRITE = os.getenv("GS_FILE_OVERWRITE", "False").strip().lower() in {'1', 'true', 'yes', 'on'}

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

if GS_BUCKET_NAME:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.gcloud.GoogleCloudStorage",
        "OPTIONS": {
            "bucket_name": GS_BUCKET_NAME,
            "project_id": GS_PROJECT_ID,
            "default_acl": GS_DEFAULT_ACL,
            "file_overwrite": GS_FILE_OVERWRITE,
            "querystring_auth": GS_QUERYSTRING_AUTH,
        },
    }

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'smartInterview.middleware.SubdomainMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'smartInterview.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ['smartInterview'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
    BASE_DIR / "angular/static/frontend/browser",
]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

WSGI_APPLICATION = 'smartInterview.wsgi.application'

# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

# DB_ENGINE = os.getenv('DB_ENGINE', '').strip().lower()
# POSTGRES_HOST = os.getenv('POSTGRES_HOST', '').strip()
# if DB_ENGINE in {'postgres', 'postgresql'} or POSTGRES_HOST:
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "shortlistii"),
        "USER": os.environ.get("DB_USER", "shortlistii_user"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Kolkata'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
# STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = env_bool('USE_X_FORWARDED_HOST', default=not DEBUG)
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', default=False)

default_shared_cookie_domain = os.getenv('SESSION_COOKIE_DOMAIN', '').strip()
if not default_shared_cookie_domain and not DEBUG:
    default_shared_cookie_domain = '.shortlistii.com'

SESSION_COOKIE_DOMAIN = default_shared_cookie_domain or None
CSRF_COOKIE_DOMAIN = os.getenv('CSRF_COOKIE_DOMAIN', '').strip() or SESSION_COOKIE_DOMAIN
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', default=not DEBUG)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', default=not DEBUG)
SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
CSRF_COOKIE_SAMESITE = os.getenv('CSRF_COOKIE_SAMESITE', 'Lax')
SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', '1209600'))
SESSION_SAVE_EVERY_REQUEST = env_bool('SESSION_SAVE_EVERY_REQUEST', default=True)
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool('SESSION_EXPIRE_AT_BROWSER_CLOSE', default=False)


REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': os.getenv('DRF_THROTTLE_ANON_RATE', '120/minute'),
        'user': os.getenv('DRF_THROTTLE_USER_RATE', '300/minute'),
        'otp_request': os.getenv('OTP_REQUEST_THROTTLE_RATE', '10/minute'),
        'otp_verify': os.getenv('OTP_VERIFY_THROTTLE_RATE', '20/minute'),
        'otp_resend': os.getenv('OTP_RESEND_THROTTLE_RATE', '5/minute'),
    },
}

NOTIFICATION_PROVIDER_MODE = os.getenv('NOTIFICATION_PROVIDER_MODE', 'real').strip().lower()
MSG91_MOCK_MODE = env_bool('MSG91_MOCK_MODE', default=False)
META_WHATSAPP_MOCK_MODE = env_bool('META_WHATSAPP_MOCK_MODE', default=False)
EXOTEL_MOCK_MODE = env_bool('EXOTEL_MOCK_MODE', default=False)

MSG91_AUTH_KEY = os.getenv('MSG91_AUTH_KEY', '')
MSG91_SENDER_ID = os.getenv('MSG91_SENDER_ID', '')
MSG91_ROUTE = os.getenv('MSG91_ROUTE', '4')
MSG91_OTP_TEMPLATE_ID = os.getenv('MSG91_OTP_TEMPLATE_ID', '')
MSG91_INTERVIEW_TEMPLATE_ID = os.getenv('MSG91_INTERVIEW_TEMPLATE_ID', '')
MSG91_CANDIDATE_SIGNUP_TEMPLATE_ID = os.getenv('MSG91_CANDIDATE_SIGNUP_TEMPLATE_ID', '')
MSG91_INTERVIEW_REMINDER_ONE_HOUR_TEMPLATE_ID = os.getenv('MSG91_INTERVIEW_REMINDER_ONE_HOUR_TEMPLATE_ID', '')
MSG91_INTERVIEW_REMINDER_THIRTY_MIN_TEMPLATE_ID = os.getenv('MSG91_INTERVIEW_REMINDER_THIRTY_MIN_TEMPLATE_ID', '')
MSG91_INTERVIEW_REMINDER_FIFTEEN_MIN_TEMPLATE_ID = os.getenv('MSG91_INTERVIEW_REMINDER_FIFTEEN_MIN_TEMPLATE_ID', '')
MSG91_OTP_LENGTH = int(os.getenv('MSG91_OTP_LENGTH', '6'))
MSG91_OTP_EXPIRY_SECONDS = int(os.getenv('MSG91_OTP_EXPIRY_SECONDS', '300'))
MSG91_OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv('MSG91_OTP_RESEND_COOLDOWN_SECONDS', '60'))
MSG91_OTP_MAX_VERIFY_ATTEMPTS = int(os.getenv('MSG91_OTP_MAX_VERIFY_ATTEMPTS', '5'))
MSG91_WEBHOOK_TOKEN = os.getenv('MSG91_WEBHOOK_TOKEN', '')
MSG91_WEBHOOK_SECRET = os.getenv('MSG91_WEBHOOK_SECRET', '')
AI_TALENT_POOL_REINDEX_DEBOUNCE_SECONDS = int(os.getenv('AI_TALENT_POOL_REINDEX_DEBOUNCE_SECONDS', '30'))

META_WHATSAPP_TOKEN = os.getenv('META_WHATSAPP_TOKEN', '')
META_WHATSAPP_PHONE_NUMBER_ID = os.getenv('META_WHATSAPP_PHONE_NUMBER_ID', '')
META_WHATSAPP_VERIFY_TOKEN = os.getenv('META_WHATSAPP_VERIFY_TOKEN', '')
META_WHATSAPP_API_VERSION = os.getenv('META_WHATSAPP_API_VERSION', 'v21.0')
META_WHATSAPP_APP_SECRET = os.getenv('META_WHATSAPP_APP_SECRET', '')
DEFAULT_WHATSAPP_LANGUAGE_CODE = os.getenv('DEFAULT_WHATSAPP_LANGUAGE_CODE', 'en')
CANDIDATE_SIGNUP_WHATSAPP_TEMPLATE = os.getenv('CANDIDATE_SIGNUP_WHATSAPP_TEMPLATE', 'candidate_signup_invite')
CANDIDATE_EXISTING_WHATSAPP_TEMPLATE = os.getenv('CANDIDATE_EXISTING_WHATSAPP_TEMPLATE', 'candidate_interview_created')
PHONE_VERIFICATION_WHATSAPP_TEMPLATE = os.getenv('PHONE_VERIFICATION_WHATSAPP_TEMPLATE', 'verify_phone_otp')

EXOTEL_SID = os.getenv('EXOTEL_SID', '')
EXOTEL_API_KEY = os.getenv('EXOTEL_API_KEY', '').strip()
EXOTEL_TOKEN = os.getenv('EXOTEL_TOKEN', '')
EXOTEL_CALLER_ID = os.getenv('EXOTEL_CALLER_ID', '')
EXOTEL_FLOW_ID = os.getenv('EXOTEL_FLOW_ID', '')
EXOTEL_SUBDOMAIN = os.getenv('EXOTEL_SUBDOMAIN', 'api.exotel.com')
EXOTEL_WEBHOOK_TOKEN = os.getenv('EXOTEL_WEBHOOK_TOKEN', '')
EXOTEL_WEBHOOK_SECRET = os.getenv('EXOTEL_WEBHOOK_SECRET', '')
EXOTEL_STATUS_CALLBACK_URL = os.getenv('EXOTEL_STATUS_CALLBACK_URL', '').strip()
EXOTEL_TIMEZONE = os.getenv('EXOTEL_TIMEZONE', 'Asia/Kolkata').strip() or 'Asia/Kolkata'

GCP_PROJECT_ID = os.getenv('GCP_PROJECT_ID', '').strip()
GCP_LOCATION = os.getenv('GCP_LOCATION', '').strip()
CLOUD_TASKS_QUEUE = os.getenv('CLOUD_TASKS_QUEUE', '').strip()
CLOUD_RUN_BASE_URL = os.getenv('CLOUD_RUN_BASE_URL', '').strip()
CLOUD_TASKS_SHARED_SECRET = os.getenv('CLOUD_TASKS_SHARED_SECRET', '').strip()
INTERVIEW_REMINDER_GRACE_SECONDS = int(os.getenv('INTERVIEW_REMINDER_GRACE_SECONDS', '120'))
INTERVIEW_REMINDER_STALE_AFTER_SECONDS = int(os.getenv('INTERVIEW_REMINDER_STALE_AFTER_SECONDS', '900'))
INTERVIEW_REMINDER_ONE_HOUR_WHATSAPP_TEMPLATE = os.getenv('INTERVIEW_REMINDER_ONE_HOUR_WHATSAPP_TEMPLATE', 'interview_reminder_one_hour').strip()
INTERVIEW_REMINDER_THIRTY_MIN_WHATSAPP_TEMPLATE = os.getenv('INTERVIEW_REMINDER_THIRTY_MIN_WHATSAPP_TEMPLATE', 'interview_reminder_thirty_min').strip()
INTERVIEW_REMINDER_FIFTEEN_MIN_WHATSAPP_TEMPLATE = os.getenv('INTERVIEW_REMINDER_FIFTEEN_MIN_WHATSAPP_TEMPLATE', 'interview_reminder_fifteen_min').strip()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.getenv('OPENAI_MODEL', '').strip() or os.getenv('OPENAI_RESUME_MODEL', 'gpt-4.1-mini').strip()
OPENAI_RESUME_MODEL = os.getenv('OPENAI_RESUME_MODEL', OPENAI_MODEL).strip()
INTERVIEW_BLUEPRINT_ENABLED = env_bool('INTERVIEW_BLUEPRINT_ENABLED', default=True)
INTERVIEW_BLUEPRINT_OPENAI_ENABLED = env_bool('INTERVIEW_BLUEPRINT_OPENAI_ENABLED', default=True)
INTERVIEW_BLUEPRINT_CREATE_MISSING_SKILLS = env_bool('INTERVIEW_BLUEPRINT_CREATE_MISSING_SKILLS', default=True)
INTERVIEW_BLUEPRINT_MAX_SKILLS = int(os.getenv('INTERVIEW_BLUEPRINT_MAX_SKILLS', '5'))
INTERVIEW_BLUEPRINT_MAX_EXTRACTED_SKILLS = int(os.getenv('INTERVIEW_BLUEPRINT_MAX_EXTRACTED_SKILLS', '20'))
INTERVIEW_RUNTIME_SUB_SKILLS_TO_PICK = int(os.getenv('INTERVIEW_RUNTIME_SUB_SKILLS_TO_PICK', '3'))
INTERVIEW_RUNTIME_PRIMARY_QUESTIONS = int(os.getenv('INTERVIEW_RUNTIME_PRIMARY_QUESTIONS', '5'))
INTERVIEW_RUNTIME_SUB_SKILL_QUESTIONS = int(os.getenv('INTERVIEW_RUNTIME_SUB_SKILL_QUESTIONS', '3'))
INTERVIEW_BLUEPRINT_OPENAI_TIMEOUT_SECONDS = int(os.getenv('INTERVIEW_BLUEPRINT_OPENAI_TIMEOUT_SECONDS', '20'))
INTERVIEW_QUESTION_BANK_ENABLED = env_bool('INTERVIEW_QUESTION_BANK_ENABLED', default=True)
INTERVIEW_QUESTION_BANK_OPENAI_ENABLED = env_bool('INTERVIEW_QUESTION_BANK_OPENAI_ENABLED', default=True)
INTERVIEW_QUESTION_BANK_AUTO_ENQUEUE_ON_BLUEPRINT = env_bool('INTERVIEW_QUESTION_BANK_AUTO_ENQUEUE_ON_BLUEPRINT', default=True)
INTERVIEW_QUESTION_BANK_PROCESS_INLINE = env_bool('INTERVIEW_QUESTION_BANK_PROCESS_INLINE', default=False)
INTERVIEW_QUESTION_BANK_RUNNER_MODE = os.getenv('INTERVIEW_QUESTION_BANK_RUNNER_MODE', 'worker_only').strip() or 'worker_only'
INTERVIEW_QUESTION_BANK_WORKER_LIMIT = int(os.getenv('INTERVIEW_QUESTION_BANK_WORKER_LIMIT', '1'))
INTERVIEW_QUESTION_BANK_MAX_SKILLS_PER_BLUEPRINT_ENQUEUE = int(os.getenv('INTERVIEW_QUESTION_BANK_MAX_SKILLS_PER_BLUEPRINT_ENQUEUE', '5'))
INTERVIEW_SKILL_VERBAL_TARGET_COUNT = int(os.getenv('INTERVIEW_SKILL_VERBAL_TARGET_COUNT', '100'))
INTERVIEW_SKILL_CODING_TARGET_COUNT = int(os.getenv('INTERVIEW_SKILL_CODING_TARGET_COUNT', '0'))
INTERVIEW_SKILL_MIN_VERBAL_READY_COUNT = int(os.getenv('INTERVIEW_SKILL_MIN_VERBAL_READY_COUNT', '30'))
INTERVIEW_SKILL_MIN_CODING_READY_COUNT = int(os.getenv('INTERVIEW_SKILL_MIN_CODING_READY_COUNT', '5'))
INTERVIEW_QUESTION_GENERATION_BATCH_SIZE = int(os.getenv('INTERVIEW_QUESTION_GENERATION_BATCH_SIZE', '10'))
INTERVIEW_QUESTION_GENERATION_TIMEOUT_SECONDS = int(os.getenv('INTERVIEW_QUESTION_GENERATION_TIMEOUT_SECONDS', '60'))
INTERVIEW_QUESTION_GENERATION_MAX_ATTEMPTS = int(os.getenv('INTERVIEW_QUESTION_GENERATION_MAX_ATTEMPTS', '3'))
INTERVIEW_QUESTION_GENERATION_STALE_RUNNING_MINUTES = int(os.getenv('INTERVIEW_QUESTION_GENERATION_STALE_RUNNING_MINUTES', '20'))
INTERVIEW_CODING_GENERATION_BATCH_SIZE = int(os.getenv('INTERVIEW_CODING_GENERATION_BATCH_SIZE', '2'))
INTERVIEW_CODING_GENERATION_TIMEOUT_SECONDS = int(os.getenv('INTERVIEW_CODING_GENERATION_TIMEOUT_SECONDS', '60'))
AI_TALENT_POOL_REQUIRE_REAL_EMBEDDINGS = env_bool(
    'AI_TALENT_POOL_REQUIRE_REAL_EMBEDDINGS',
    default=not DEBUG,
)
AI_TALENT_POOL_EMBEDDING_MODEL = 'all-MiniLM-L6-v2'
AI_TALENT_POOL_ENABLE_HASHED_EMBEDDING_FALLBACK = env_bool(
    'AI_TALENT_POOL_ENABLE_HASHED_EMBEDDING_FALLBACK',
    default=DEBUG,
)
AI_TALENT_POOL_SENTENCE_TRANSFORMERS_CACHE_DIR = os.getenv(
    'AI_TALENT_POOL_SENTENCE_TRANSFORMERS_CACHE_DIR',
    str(BASE_DIR / '.cache' / 'sentence-transformers'),
).strip()
AI_TALENT_POOL_DEBUG_LOGGING = env_bool(
    'AI_TALENT_POOL_DEBUG_LOGGING',
    default=DEBUG,
)
AI_TALENT_POOL_REQUIRE_PGVECTOR = env_bool(
    'AI_TALENT_POOL_REQUIRE_PGVECTOR',
    default=not DEBUG,
)
AI_TALENT_POOL_ENABLE_LOCAL_INDEX_SCAN_FALLBACK = env_bool(
    'AI_TALENT_POOL_ENABLE_LOCAL_INDEX_SCAN_FALLBACK',
    default=DEBUG,
)
AI_TALENT_POOL_ENABLE_STRICT_SUBFAMILY_PREFILTER = env_bool(
    'AI_TALENT_POOL_ENABLE_STRICT_SUBFAMILY_PREFILTER',
    default=False,
)
AI_TALENT_POOL_RETRIEVAL_SHORTLIST_SIZE = int(os.getenv('AI_TALENT_POOL_RETRIEVAL_SHORTLIST_SIZE', '200'))
AI_TALENT_POOL_WEIGHT_SEMANTIC_SIMILARITY = float(os.getenv('AI_TALENT_POOL_WEIGHT_SEMANTIC_SIMILARITY', '0.35'))
AI_TALENT_POOL_WEIGHT_MUST_HAVE_SKILLS = float(os.getenv('AI_TALENT_POOL_WEIGHT_MUST_HAVE_SKILLS', '0.25'))
AI_TALENT_POOL_WEIGHT_PREFERRED_SKILLS = float(os.getenv('AI_TALENT_POOL_WEIGHT_PREFERRED_SKILLS', '0.10'))
AI_TALENT_POOL_WEIGHT_EXPERIENCE_FIT = float(os.getenv('AI_TALENT_POOL_WEIGHT_EXPERIENCE_FIT', '0.10'))
AI_TALENT_POOL_WEIGHT_TITLE_SIMILARITY = float(os.getenv('AI_TALENT_POOL_WEIGHT_TITLE_SIMILARITY', '0.10'))
AI_TALENT_POOL_WEIGHT_LOCATION_MATCH = float(os.getenv('AI_TALENT_POOL_WEIGHT_LOCATION_MATCH', '0.05'))
AI_TALENT_POOL_WEIGHT_PIPELINE_SIGNAL = float(os.getenv('AI_TALENT_POOL_WEIGHT_PIPELINE_SIGNAL', '0.05'))
AI_TALENT_POOL_SPARSE_WEIGHT_SEMANTIC_SIMILARITY = float(os.getenv('AI_TALENT_POOL_SPARSE_WEIGHT_SEMANTIC_SIMILARITY', '0.30'))
AI_TALENT_POOL_SPARSE_WEIGHT_MUST_HAVE_SKILLS = float(os.getenv('AI_TALENT_POOL_SPARSE_WEIGHT_MUST_HAVE_SKILLS', '0.20'))
AI_TALENT_POOL_SPARSE_WEIGHT_PREFERRED_SKILLS = float(os.getenv('AI_TALENT_POOL_SPARSE_WEIGHT_PREFERRED_SKILLS', '0.05'))
AI_TALENT_POOL_SPARSE_WEIGHT_EXPERIENCE_FIT = float(os.getenv('AI_TALENT_POOL_SPARSE_WEIGHT_EXPERIENCE_FIT', '0.15'))
AI_TALENT_POOL_SPARSE_WEIGHT_TITLE_SIMILARITY = float(os.getenv('AI_TALENT_POOL_SPARSE_WEIGHT_TITLE_SIMILARITY', '0.15'))
AI_TALENT_POOL_SPARSE_WEIGHT_LOCATION_MATCH = float(os.getenv('AI_TALENT_POOL_SPARSE_WEIGHT_LOCATION_MATCH', '0.05'))
AI_TALENT_POOL_SPARSE_WEIGHT_PIPELINE_SIGNAL = float(os.getenv('AI_TALENT_POOL_SPARSE_WEIGHT_PIPELINE_SIGNAL', '0.10'))
AI_TALENT_POOL_SPARSE_ROLE_CONFIDENCE_PENALTY = float(os.getenv('AI_TALENT_POOL_SPARSE_ROLE_CONFIDENCE_PENALTY', '0.72'))
AI_TALENT_POOL_MEDIUM_CONFIDENCE_PENALTY = float(os.getenv('AI_TALENT_POOL_MEDIUM_CONFIDENCE_PENALTY', '0.88'))
AI_TALENT_POOL_GRAPH_EXACT_MATCH_BONUS = float(os.getenv('AI_TALENT_POOL_GRAPH_EXACT_MATCH_BONUS', '0.00'))
AI_TALENT_POOL_GRAPH_RELATED_MATCH_CAP = float(os.getenv('AI_TALENT_POOL_GRAPH_RELATED_MATCH_CAP', '0.92'))
AI_TALENT_POOL_GRAPH_TITLE_ADJACENCY_BLEND = float(os.getenv('AI_TALENT_POOL_GRAPH_TITLE_ADJACENCY_BLEND', '0.65'))
AI_TALENT_POOL_GRAPH_FAMILY_ALIGNMENT_BONUS = float(os.getenv('AI_TALENT_POOL_GRAPH_FAMILY_ALIGNMENT_BONUS', '0.08'))
AI_TALENT_POOL_SEMANTIC_FLOOR_FULL_MATCH = float(os.getenv('AI_TALENT_POOL_SEMANTIC_FLOOR_FULL_MATCH', '0.72'))
AI_TALENT_POOL_SEMANTIC_FLOOR_STRONG_ADJACENT = float(os.getenv('AI_TALENT_POOL_SEMANTIC_FLOOR_STRONG_ADJACENT', '0.58'))

NOTIFICATION_RETRY_LIMIT = int(os.getenv('NOTIFICATION_RETRY_LIMIT', '2'))
NOTIFICATION_RETRY_BACKOFF_SECONDS = int(os.getenv('NOTIFICATION_RETRY_BACKOFF_SECONDS', '10'))
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.smtp.EmailBackend',
)
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@shortlistii.com')
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', default=True)
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', default=False)
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '20'))
EMAIL_OTP_EXPIRY_SECONDS = int(os.getenv('EMAIL_OTP_EXPIRY_SECONDS', str(MSG91_OTP_EXPIRY_SECONDS)))
EMAIL_OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv('EMAIL_OTP_RESEND_COOLDOWN_SECONDS', str(MSG91_OTP_RESEND_COOLDOWN_SECONDS)))
EMAIL_OTP_MAX_VERIFY_ATTEMPTS = int(os.getenv('EMAIL_OTP_MAX_VERIFY_ATTEMPTS', str(MSG91_OTP_MAX_VERIFY_ATTEMPTS)))

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'structured': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'structured',
        },
    },
    'loggers': {
        'smartInterview.notifications': {
            'handlers': ['console'],
            'level': os.getenv('NOTIFICATION_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'smartInterview.company_enrichment': {
            'handlers': ['console'],
            'level': os.getenv('COMPANY_ENRICHMENT_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'smartInterview.interview_blueprints': {
            'handlers': ['console'],
            'level': os.getenv('INTERVIEW_BLUEPRINT_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'smartInterview.question_banks': {
            'handlers': ['console'],
            'level': os.getenv('INTERVIEW_QUESTION_BANK_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
    },
}
