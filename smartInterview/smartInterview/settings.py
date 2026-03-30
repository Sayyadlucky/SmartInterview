import os
from pathlib import Path


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure--o3*fivnd_=lrfz$6(@9$bsiynr(hv1+!#fd+0o@3m*_7#nfj+'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = ['*']

CSRF_TRUSTED_ORIGINS = [
    "https://shortlistii.com",
    "https://candidates.shortlistii.com",
    "https://jobs.shortlistii.com",
]


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
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
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

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
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

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


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
MSG91_OTP_LENGTH = int(os.getenv('MSG91_OTP_LENGTH', '6'))
MSG91_OTP_EXPIRY_SECONDS = int(os.getenv('MSG91_OTP_EXPIRY_SECONDS', '300'))
MSG91_OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv('MSG91_OTP_RESEND_COOLDOWN_SECONDS', '60'))
MSG91_OTP_MAX_VERIFY_ATTEMPTS = int(os.getenv('MSG91_OTP_MAX_VERIFY_ATTEMPTS', '5'))
MSG91_WEBHOOK_TOKEN = os.getenv('MSG91_WEBHOOK_TOKEN', '')
MSG91_WEBHOOK_SECRET = os.getenv('MSG91_WEBHOOK_SECRET', '')

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
EXOTEL_TOKEN = os.getenv('EXOTEL_TOKEN', '')
EXOTEL_CALLER_ID = os.getenv('EXOTEL_CALLER_ID', '')
EXOTEL_FLOW_ID = os.getenv('EXOTEL_FLOW_ID', '')
EXOTEL_SUBDOMAIN = os.getenv('EXOTEL_SUBDOMAIN', 'api.exotel.com')
EXOTEL_WEBHOOK_TOKEN = os.getenv('EXOTEL_WEBHOOK_TOKEN', '')
EXOTEL_WEBHOOK_SECRET = os.getenv('EXOTEL_WEBHOOK_SECRET', '')

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.getenv('OPENAI_MODEL', '').strip() or os.getenv('OPENAI_RESUME_MODEL', 'gpt-4.1-mini').strip()
OPENAI_RESUME_MODEL = os.getenv('OPENAI_RESUME_MODEL', OPENAI_MODEL).strip()

NOTIFICATION_RETRY_LIMIT = int(os.getenv('NOTIFICATION_RETRY_LIMIT', '2'))
NOTIFICATION_RETRY_BACKOFF_SECONDS = int(os.getenv('NOTIFICATION_RETRY_BACKOFF_SECONDS', '10'))
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@smartinterview.local')
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
    },
}
