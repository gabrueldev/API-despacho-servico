from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "django_celery_beat",
    "core",
    "apps.contas",
    "apps.clientes",
    "apps.chamados",
    "apps.prestadores",
    "apps.precos",
    "apps.financeiro",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Banco: PostGIS com pool nativo do psycopg 3 (exige CONN_MAX_AGE = 0, o padrão).
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["OPTIONS"] = {
    "pool": {"min_size": 2, "max_size": env.int("DB_POOL_MAX", default=10)},
}

# Só necessários fora do Docker (ex.: macOS com Homebrew).
GDAL_LIBRARY_PATH = env("GDAL_LIBRARY_PATH", default=None)
GEOS_LIBRARY_PATH = env("GEOS_LIBRARY_PATH", default=None)

REDIS_URL = env("REDIS_URL")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

AUTH_USER_MODEL = "contas.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Atrás do Nginx
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.CriadoEmCursorPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.exceptions.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        # App envia a cada 15 s (4/min); folga para reenvios.
        "localizacao": "6/min",
        "login": "10/min",
        # Link público: por IP (anônimo); o cache de 5 s absorve o resto.
        "rastreio": "60/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "UPDATE_LAST_LOGIN": False,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Despacha API",
    "DESCRIPTION": "API de despacho de serviços (guincho, entregas, manutenção).",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {"StatusChamadoEnum": "apps.chamados.models.Status"},
}

# Celery: filas separadas para um fechamento demorado nunca atrasar um timeout.
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True  # tarefas são idempotentes: reentregar é seguro
CELERY_TASK_SOFT_TIME_LIMIT = 60
CELERY_TASK_TIME_LIMIT = 90
CELERY_TASK_DEFAULT_QUEUE = "notificacoes"
CELERY_TASK_ROUTES = {
    "apps.chamados.tasks.*": {"queue": "critica"},
    "core.tasks.notificar": {"queue": "notificacoes"},
    "core.tasks.limpar_idempotency_keys": {"queue": "pesada"},
    "apps.prestadores.tasks.*": {"queue": "pesada"},
}
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TIMEZONE = TIME_ZONE

# Domínio
ACEITE_TIMEOUT_SEGUNDOS = env.int("ACEITE_TIMEOUT_SEGUNDOS", default=120)
RAIO_BUSCA_KM = env.int("RAIO_BUSCA_KM", default=30)
RAIO_BUSCA_MAX_KM = 100
PROXIMOS_LIMITE = 20
# Prestador sem posição nova há mais que isso some da busca (app fechado/sem sinal).
POSICAO_VALIDADE_MINUTOS = env.int("POSICAO_VALIDADE_MINUTOS", default=10)
RASTREIO_CACHE_SEGUNDOS = 5
RASTREIO_VALIDADE_HORAS = env.int("RASTREIO_VALIDADE_HORAS", default=24)
LOCALIZACAO_FLUSH_SEGUNDOS = env.int("LOCALIZACAO_FLUSH_SEGUNDOS", default=60)
IDEMPOTENCY_TTL_HORAS = env.int("IDEMPOTENCY_TTL_HORAS", default=24)
NOTIFICADOR = env("NOTIFICADOR", default="core.notificacoes.LogNotificador")

CELERY_BEAT_SCHEDULE = {
    "gravar-localizacoes": {
        "task": "apps.prestadores.tasks.gravar_localizacoes",
        "schedule": float(LOCALIZACAO_FLUSH_SEGUNDOS),
    },
    "limpar-idempotency-keys": {
        "task": "core.tasks.limpar_idempotency_keys",
        "schedule": 60.0 * 60,
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
