from typing import Any

from django.conf import settings
from django.core.cache import cache
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from apps.contas.models import Papel, Usuario
from apps.contas.permissions import tem_papel
from core import idempotencia

from .. import selectors, services
from ..models import Chamado, Status
from .serializers import (
    AvancarSerializer,
    CancelarSerializer,
    ChamadoCriadoSerializer,
    ChamadoCriarSerializer,
    ChamadoDetalheSerializer,
    ChamadoEstadoSerializer,
    ChamadoListaSerializer,
    DespacharSerializer,
    RastreioSerializer,
    RecusarSerializer,
)

PODE_VER = tem_papel(Papel.ATENDENTE, Papel.DESPACHANTE, Papel.PRESTADOR)
PODE_CRIAR = tem_papel(Papel.ATENDENTE)
SO_PRESTADOR = tem_papel(Papel.PRESTADOR)
PODE_CANCELAR = tem_papel(Papel.ATENDENTE, Papel.DESPACHANTE)
PODE_DESPACHAR = tem_papel(Papel.DESPACHANTE)


class ChamadoListaView(generics.ListCreateAPIView[Chamado]):
    def get_permissions(self) -> list[BasePermission]:
        return [PODE_CRIAR() if self.request.method == "POST" else PODE_VER()]

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        return ChamadoCriarSerializer if self.request.method == "POST" else ChamadoListaSerializer

    def get_queryset(self) -> Any:
        filtro = self.request.query_params.get("status")
        if filtro and filtro not in Status.values:
            raise ValidationError({"status": f"Use um de: {', '.join(Status.values)}."})
        return selectors.listar_chamados(self.request.user, Status(filtro) if filtro else None)  # type: ignore[arg-type]

    @extend_schema(parameters=[OpenApiParameter("status", enum=Status.values)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=ChamadoCriarSerializer,
        responses={201: ChamadoCriadoSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=False,
                description="Reenvio com a mesma chave devolve o mesmo chamado, sem duplicar.",
            )
        ],
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        entrada = ChamadoCriarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        usuario: Usuario = request.user  # type: ignore[assignment]

        def operacao() -> idempotencia.Resultado:
            criado = services.criar_chamado(
                atendente=usuario, dados=services.NovoChamado(**entrada.validated_data)
            )
            saida = ChamadoCriadoSerializer(criado.chamado, context={"itens": criado.itens})
            return idempotencia.Resultado(status.HTTP_201_CREATED, saida.data)

        chave = request.headers.get("Idempotency-Key")
        if chave is None:
            resultado = operacao()
        else:
            resultado = idempotencia.executar(
                usuario=usuario, chave=chave, dados=request.data, operacao=operacao
            )
        response = Response(resultado.corpo, status=resultado.status_code)
        if resultado.repetido:
            response["Idempotent-Replayed"] = "true"
        return response


class ChamadoDetalheView(generics.RetrieveAPIView[Chamado]):
    permission_classes = [PODE_VER]
    serializer_class = ChamadoDetalheSerializer

    def get_queryset(self) -> Any:
        return selectors.detalhe_chamados(self.request.user)  # type: ignore[arg-type]


def _estado(chamado: Chamado) -> Response:
    return Response(ChamadoEstadoSerializer(chamado).data)


def _validar(serializer_class: type[BaseSerializer[Any]], request: Request) -> dict[str, Any]:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data  # type: ignore[no-any-return]


class DespacharView(APIView):
    permission_classes = [PODE_DESPACHAR]

    @extend_schema(
        request=DespacharSerializer,
        responses={200: ChamadoEstadoSerializer, 409: dict},
        description="Trava chamado e prestador com NOWAIT; quem perde recebe 409 na hora.",
    )
    def post(self, request: Request, pk: int) -> Response:
        dados = _validar(DespacharSerializer, request)
        chamado = services.despachar(
            usuario=request.user,  # type: ignore[arg-type]
            chamado_id=pk,
            prestador_id=dados["prestador_id"],
        )
        return _estado(chamado)


class AceitarView(APIView):
    permission_classes = [SO_PRESTADOR]

    @extend_schema(request=None, responses=ChamadoEstadoSerializer)
    def post(self, request: Request, pk: int) -> Response:
        return _estado(services.aceitar(usuario=request.user, chamado_id=pk))  # type: ignore[arg-type]


class RecusarView(APIView):
    permission_classes = [SO_PRESTADOR]

    @extend_schema(request=RecusarSerializer, responses=ChamadoEstadoSerializer)
    def post(self, request: Request, pk: int) -> Response:
        dados = _validar(RecusarSerializer, request)
        return _estado(services.recusar(usuario=request.user, chamado_id=pk, **dados))  # type: ignore[arg-type]


class AvancarView(APIView):
    permission_classes = [SO_PRESTADOR]

    @extend_schema(request=AvancarSerializer, responses=ChamadoEstadoSerializer)
    def post(self, request: Request, pk: int) -> Response:
        dados = _validar(AvancarSerializer, request)
        chamado = services.avancar(
            usuario=request.user,  # type: ignore[arg-type]
            chamado_id=pk,
            status=Status(dados["status"]),
        )
        return _estado(chamado)


class ConcluirView(APIView):
    permission_classes = [SO_PRESTADOR]

    @extend_schema(request=None, responses=ChamadoEstadoSerializer)
    def post(self, request: Request, pk: int) -> Response:
        return _estado(services.concluir(usuario=request.user, chamado_id=pk))  # type: ignore[arg-type]


class CancelarView(APIView):
    permission_classes = [PODE_CANCELAR]

    @extend_schema(request=CancelarSerializer, responses=ChamadoEstadoSerializer)
    def post(self, request: Request, pk: int) -> Response:
        dados = _validar(CancelarSerializer, request)
        return _estado(services.cancelar(usuario=request.user, chamado_id=pk, **dados))  # type: ignore[arg-type]


class RastreioView(APIView):
    """Link público para o associado (sem login).

    Resposta inteira em cache por 5 s: vários aparelhos abrindo o mesmo link viram uma query
    a cada 5 s. Só respostas 200 entram no cache; o rate limit é por IP.
    """

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]
    throttle_scope = "rastreio"

    @extend_schema(responses={200: dict, 404: dict, 410: dict})
    def get(self, request: Request, token: str) -> Response:
        chave = f"rastreio:{token}"
        corpo = cache.get(chave)
        if corpo is None:
            corpo = RastreioSerializer(selectors.rastreio(token)).data
            cache.set(chave, corpo, timeout=settings.RASTREIO_CACHE_SEGUNDOS)
        return Response(corpo)
