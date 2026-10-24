import re
from typing import Any

from rest_framework import serializers

from core.fields import PontoField

from ..estados import AVANCOS_DO_PRESTADOR
from ..models import Chamado, EventoChamado, ItemValor, Status

# Antiga (ABC1234) ou Mercosul (ABC1D23); aceita com hífen/minúsculas e normaliza.
PLACA_RE = re.compile(r"^[A-Z]{3}\d[A-Z0-9]\d{2}$")


class ChamadoCriarSerializer(serializers.Serializer[Any]):
    cliente_id = serializers.IntegerField(min_value=1)
    placa = serializers.CharField(max_length=8)
    endereco_origem = serializers.CharField(max_length=255)
    origem = PontoField()
    destino = PontoField()

    def validate_placa(self, value: str) -> str:
        placa = value.replace("-", "").strip().upper()
        if not PLACA_RE.match(placa):
            raise serializers.ValidationError("Placa inválida.")
        return placa


class ClienteResumoSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class PrestadorResumoSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class ItemValorSerializer(serializers.ModelSerializer[ItemValor]):
    class Meta:
        model = ItemValor
        fields = ("id", "tipo", "descricao", "quantidade", "valor_unitario", "total")


class EventoChamadoSerializer(serializers.ModelSerializer[EventoChamado]):
    class Meta:
        model = EventoChamado
        fields = ("id", "usuario_id", "de_status", "para_status", "dados", "criado_em")


class ChamadoListaSerializer(serializers.ModelSerializer[Chamado]):
    cliente = ClienteResumoSerializer()
    prestador = PrestadorResumoSerializer(allow_null=True)

    class Meta:
        model = Chamado
        fields = (
            "id",
            "status",
            "placa",
            "cliente",
            "prestador",
            "valor_previsto",
            "valor_final",
            "criado_em",
        )


class ChamadoDetalheSerializer(serializers.ModelSerializer[Chamado]):
    cliente = ClienteResumoSerializer()
    prestador = PrestadorResumoSerializer(allow_null=True)
    origem = PontoField()
    destino = PontoField()
    itens = ItemValorSerializer(many=True)
    eventos = EventoChamadoSerializer(many=True)

    class Meta:
        model = Chamado
        fields = (
            "id",
            "status",
            "placa",
            "cliente",
            "prestador",
            "endereco_origem",
            "origem",
            "destino",
            "distancia_km",
            "valor_previsto",
            "valor_final",
            "rastreio_token",
            "criado_em",
            "atualizado_em",
            "encerrado_em",
            "version",
            "itens",
            "eventos",
        )


class ChamadoCriadoSerializer(serializers.ModelSerializer[Chamado]):
    """Resposta do POST montada com o que já está em memória — sem nova ida ao banco."""

    itens = serializers.SerializerMethodField()

    class Meta:
        model = Chamado
        fields = (
            "id",
            "status",
            "placa",
            "cliente_id",
            "distancia_km",
            "valor_previsto",
            "rastreio_token",
            "criado_em",
            "itens",
        )

    def get_itens(self, obj: Chamado) -> list[dict[str, Any]]:
        return ItemValorSerializer(self.context["itens"], many=True).data  # type: ignore[return-value]


class ChamadoEstadoSerializer(serializers.Serializer[Any]):
    """Resposta das ações de ciclo de vida: só o que muda, já em memória."""

    id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Status.choices)
    version = serializers.IntegerField()
    valor_final = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    encerrado_em = serializers.DateTimeField(allow_null=True)


class RecusarSerializer(serializers.Serializer[Any]):
    motivo = serializers.CharField(max_length=255, required=False, default="")


class CancelarSerializer(serializers.Serializer[Any]):
    motivo = serializers.CharField(max_length=255)


class AvancarSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=[(s.value, s.label) for s in AVANCOS_DO_PRESTADOR])


class DespacharSerializer(serializers.Serializer[Any]):
    prestador_id = serializers.IntegerField(min_value=1)
