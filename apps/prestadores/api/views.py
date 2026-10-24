from dataclasses import asdict
from typing import Any

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTStatelessUserAuthentication

from apps.contas.models import Papel
from apps.contas.permissions import tem_papel
from core.exceptions import NaoEncontrado
from core.fields import PontoField

from .. import localizacao, selectors
from ..models import Prestador


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


class MinhaPosicaoSerializer(serializers.Serializer[Any]):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    registrado_em = serializers.CharField(allow_null=True)


class MeuPerfilSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    disponivel = serializers.BooleanField()
    posicao = MinhaPosicaoSerializer(allow_null=True)


class MeuPerfilView(APIView):
    """Quem sou e onde estou: 1 query (índice único de `usuario_id`) + 1 leitura no Redis.

    A posição vem do Redis (a mais recente); sem ela, a última gravada no banco.
    """

    permission_classes = [tem_papel(Papel.PRESTADOR)]

    @extend_schema(responses=MeuPerfilSerializer)
    def get(self, request: Request) -> Response:
        usuario_id: int = request.user.pk  # type: ignore[assignment]
        prestador = (
            Prestador.objects.only("id", "nome", "disponivel", "localizacao")
            .filter(usuario_id=usuario_id)
            .first()
        )
        if prestador is None:
            raise NaoEncontrado("Este usuário não tem cadastro de prestador.")
        posicao = localizacao.ultima_posicao(usuario_id)
        if posicao is None and prestador.localizacao:
            posicao = {
                "lat": prestador.localizacao.y,
                "lng": prestador.localizacao.x,
                "registrado_em": None,
            }
        return Response(
            {
                "id": prestador.pk,
                "nome": prestador.nome,
                "disponivel": prestador.disponivel,
                "posicao": posicao,
            }
        )


class ProximosQuerySerializer(serializers.Serializer[Any]):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)
    raio = serializers.FloatField(
        min_value=0.1,
        max_value=settings.RAIO_BUSCA_MAX_KM,
        default=settings.RAIO_BUSCA_KM,
        help_text="Raio em km.",
    )


class PrestadorProximoSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    telefone = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    distancia_km = serializers.DecimalField(max_digits=8, decimal_places=2)


class ProximosView(APIView):
    """Disponíveis no raio, do mais próximo ao mais distante (o 1º é a sugestão automática)."""

    permission_classes = [tem_papel(Papel.DESPACHANTE, Papel.ATENDENTE)]

    @extend_schema(
        parameters=[ProximosQuerySerializer],
        responses=PrestadorProximoSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        filtro = ProximosQuerySerializer(data=request.query_params)
        filtro.is_valid(raise_exception=True)
        dados = filtro.validated_data
        encontrados = selectors.proximos(lat=dados["lat"], lng=dados["lng"], raio_km=dados["raio"])
        return Response(
            PrestadorProximoSerializer([asdict(p) for p in encontrados], many=True).data
        )
