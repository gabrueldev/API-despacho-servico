from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response


@extend_schema(responses={200: dict, 503: dict})
@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def health(request: Request) -> Response:
    checks = {"db": _check_db(), "redis": _check_redis()}
    ok = all(checks.values())
    return Response(
        {"status": "ok" if ok else "degraded", **checks},
        status=200 if ok else 503,
    )


def _check_db() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


def _check_redis() -> bool:
    try:
        cache.set("health", "1", timeout=5)
        return bool(cache.get("health") == "1")
    except Exception:
        return False
