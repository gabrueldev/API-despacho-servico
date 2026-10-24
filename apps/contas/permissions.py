from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from .models import Papel


def tem_papel(*papeis: Papel) -> type[BasePermission]:
    """Uso: `permission_classes = [tem_papel(Papel.DESPACHANTE)]`. ADMIN sempre passa."""

    permitidos = {*papeis, Papel.ADMIN}

    class TemPapel(BasePermission):
        def has_permission(self, request: Request, view: Any) -> bool:
            user = request.user
            return bool(user and user.is_authenticated and user.papel in permitidos)

    TemPapel.__name__ = "TemPapel_" + "_".join(sorted(permitidos))
    return TemPapel
