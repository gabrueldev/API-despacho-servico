from typing import Any

from django.urls import path
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import Token
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


class LoginSerializer(TokenObtainPairSerializer):
    """Inclui `papel` no token: rotas quentes autenticam sem ir ao banco (ver localização)."""

    @classmethod
    def get_token(cls, user: Any) -> Token:
        token = super().get_token(user)
        token["papel"] = user.papel
        return token


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_scope = "login"


urlpatterns = [
    path("login", LoginView.as_view(), name="login"),
    path("refresh", TokenRefreshView.as_view(), name="refresh"),
]
