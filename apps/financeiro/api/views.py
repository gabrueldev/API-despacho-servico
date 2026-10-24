import re
from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.contas.models import Papel
from apps.contas.permissions import tem_papel

from .. import selectors, services, tasks
from ..models import Fechamento, FechamentoItem, TipoFechamento

SO_FINANCEIRO = tem_papel(Papel.FINANCEIRO)
PERIODO_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class DestinatarioSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField()
    nome = serializers.CharField()


CAMPOS_FECHAMENTO: tuple[str, ...] = (
    "id",
    "tipo",
    "cliente",
    "prestador",
    "periodo_inicio",
    "periodo_fim",
    "total",
    "quantidade_chamados",
    "status",
    "criado_em",
)


class FechamentoSerializer(serializers.ModelSerializer[Fechamento]):
    cliente = DestinatarioSerializer(allow_null=True)
    prestador = DestinatarioSerializer(allow_null=True)

    class Meta:
        model = Fechamento
        fields = CAMPOS_FECHAMENTO


class FechamentoItemSerializer(serializers.ModelSerializer[FechamentoItem]):
    chamado_id = serializers.IntegerField(source="chamado.id")
    placa = serializers.CharField(source="chamado.placa")
    status_chamado = serializers.CharField(source="chamado.status")
    encerrado_em = serializers.DateTimeField(source="chamado.encerrado_em")

    class Meta:
        model = FechamentoItem
        fields = ("chamado_id", "placa", "status_chamado", "encerrado_em", "valor")


class FechamentoDetalheSerializer(FechamentoSerializer):
    itens = FechamentoItemSerializer(many=True)

    class Meta(FechamentoSerializer.Meta):
        fields = (*CAMPOS_FECHAMENTO, "itens")


class GerarSerializer(serializers.Serializer[Any]):
    ano = serializers.IntegerField(min_value=2000, max_value=2100)
    mes = serializers.IntegerField(min_value=1, max_value=12)


def _periodo(valor: str | None) -> tuple[int, int] | tuple[None, None]:
    if not valor:
        return None, None
    m = PERIODO_RE.match(valor)
    if not m:
        raise ValidationError({"periodo": "Use AAAA-MM."})
    return int(m.group(1)), int(m.group(2))


class FechamentoListaView(generics.ListAPIView[Fechamento]):
    permission_classes = [SO_FINANCEIRO]
    serializer_class = FechamentoSerializer

    def get_queryset(self) -> Any:
        tipo = self.request.query_params.get("tipo")
        if tipo and tipo not in TipoFechamento.values:
            raise ValidationError({"tipo": f"Use {' ou '.join(TipoFechamento.values)}."})
        ano, mes = _periodo(self.request.query_params.get("periodo"))
        return selectors.listar(tipo=TipoFechamento(tipo) if tipo else None, ano=ano, mes=mes)

    @extend_schema(
        parameters=[
            OpenApiParameter("tipo", enum=TipoFechamento.values),
            OpenApiParameter("periodo", description="AAAA-MM"),
        ]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class FechamentoDetalheView(generics.RetrieveAPIView[Fechamento]):
    permission_classes = [SO_FINANCEIRO]
    serializer_class = FechamentoDetalheSerializer

    def get_queryset(self) -> Any:
        return selectors.detalhe()


class GerarFechamentosView(APIView):
    """Dispara a geração em segundo plano (fila `pesada`). Pode ser repetida sem duplicar."""

    permission_classes = [SO_FINANCEIRO]

    @extend_schema(request=GerarSerializer, responses={202: dict})
    def post(self, request: Request) -> Response:
        entrada = GerarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        ano, mes = entrada.validated_data["ano"], entrada.validated_data["mes"]
        periodo = services.Periodo.mes(ano, mes)
        # Valida aqui para responder 422 na hora, em vez de falhar calado no worker.
        services.exigir_periodo_encerrado(periodo)
        resultado = tasks.gerar_fechamentos.delay(ano, mes)
        return Response(
            {"tarefa": resultado.id, "periodo": f"{ano:04d}-{mes:02d}"},
            status=status.HTTP_202_ACCEPTED,
        )
