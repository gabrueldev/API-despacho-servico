from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from apps.contas.models import Papel
from apps.contas.permissions import tem_papel

from .. import selectors, services
from ..models import Chamado, Status
from .serializers import (
    ChamadoCriadoSerializer,
    ChamadoCriarSerializer,
    ChamadoDetalheSerializer,
    ChamadoListaSerializer,
)

PODE_VER = tem_papel(Papel.ATENDENTE, Papel.DESPACHANTE, Papel.PRESTADOR)
PODE_CRIAR = tem_papel(Papel.ATENDENTE)


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

    @extend_schema(request=ChamadoCriarSerializer, responses={201: ChamadoCriadoSerializer})
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        entrada = ChamadoCriarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        criado = services.criar_chamado(
            atendente=request.user,  # type: ignore[arg-type]
            dados=services.NovoChamado(**entrada.validated_data),
        )
        saida = ChamadoCriadoSerializer(criado.chamado, context={"itens": criado.itens})
        return Response(saida.data, status=status.HTTP_201_CREATED)


class ChamadoDetalheView(generics.RetrieveAPIView[Chamado]):
    permission_classes = [PODE_VER]
    serializer_class = ChamadoDetalheSerializer

    def get_queryset(self) -> Any:
        return selectors.detalhe_chamados(self.request.user)  # type: ignore[arg-type]
