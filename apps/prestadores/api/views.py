from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTStatelessUserAuthentication

from apps.contas.models import Papel
from apps.contas.permissions import tem_papel
from core.fields import PontoField

from .. import localizacao


class LocalizacaoSerializer(serializers.Serializer[Any]):
    posicao = PontoField()


class LocalizacaoRespostaSerializer(serializers.Serializer[Any]):
    mudou = serializers.BooleanField()


class MinhaLocalizacaoView(APIView):
    """Rota mais quente da API (cada prestador a cada ~15 s): **zero queries no Postgres**.

    Autenticação sem estado (id e papel vêm do próprio JWT) e escrita só no Redis.
    Trade-off: um usuário desativado segue enviando até o access token expirar (15 min).
    """

    authentication_classes = [JWTStatelessUserAuthentication]
    permission_classes = [tem_papel(Papel.PRESTADOR)]
    throttle_scope = "localizacao"

    @extend_schema(request=LocalizacaoSerializer, responses=LocalizacaoRespostaSerializer)
    def post(self, request: Request) -> Response:
        entrada = LocalizacaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        ponto = entrada.validated_data["posicao"]
        usuario_id: int = request.user.pk  # type: ignore[assignment]
        mudou = localizacao.registrar(usuario_id, lat=ponto.y, lng=ponto.x)
        return Response({"mudou": mudou})
