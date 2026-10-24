import secrets

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BrinIndex
from django.db.models import Q

from apps.clientes.models import Cliente
from apps.precos.tipos import TipoItem
from apps.prestadores.models import Prestador


class Status(models.TextChoices):
    ABERTO = "ABERTO", "Aberto"
    DESPACHADO = "DESPACHADO", "Despachado"
    ACEITO = "ACEITO", "Aceito"
    A_CAMINHO = "A_CAMINHO", "A caminho"
    NO_LOCAL = "NO_LOCAL", "No local"
    EM_ATENDIMENTO = "EM_ATENDIMENTO", "Em atendimento"
    CONCLUIDO = "CONCLUIDO", "Concluído"
    CANCELADO = "CANCELADO", "Cancelado"


ENCERRADOS = (Status.CONCLUIDO, Status.CANCELADO)


def gerar_token_rastreio() -> str:
    return secrets.token_urlsafe(16)


class Chamado(models.Model):
    # db_index=False nas FKs cobertas por índices compostos: um índice a menos por INSERT/UPDATE.
    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, related_name="chamados", db_index=False
    )
    atendente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", db_index=False
    )
    prestador = models.ForeignKey(
        Prestador,
        on_delete=models.PROTECT,
        related_name="chamados",
        null=True,
        blank=True,
        db_index=False,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ABERTO)
    placa = models.CharField(max_length=7)
    endereco_origem = models.CharField(max_length=255)
    # Sem busca espacial em chamados: dispensa o GiST e barateia a escrita.
    origem = models.PointField(geography=True, srid=4326, spatial_index=False)
    destino = models.PointField(geography=True, srid=4326, spatial_index=False)
    distancia_km = models.DecimalField(max_digits=8, decimal_places=2)
    valor_previsto = models.DecimalField(max_digits=12, decimal_places=2)
    valor_final = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    # Conclusão ou cancelamento: é a data que conta para o fechamento do período.
    encerrado_em = models.DateTimeField(null=True, blank=True)
    rastreio_token = models.CharField(
        max_length=32, unique=True, default=gerar_token_rastreio, editable=False
    )
    rastreio_expira_em = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [
            models.Index(fields=["criado_em", "id"], name="chamado_criado"),
            models.Index(fields=["status", "criado_em", "id"], name="chamado_status_criado"),
            models.Index(
                fields=["criado_em", "id"],
                condition=~Q(status__in=ENCERRADOS),
                name="chamado_ativos",
            ),
            models.Index(fields=["prestador", "criado_em", "id"], name="chamado_prestador_criado"),
            # Fechamento: varre o mês inteiro de todos os clientes/prestadores. Parcial: chamado
            # em andamento (encerrado_em nulo) não entra no índice nem paga por ele na escrita.
            models.Index(
                fields=["encerrado_em"],
                condition=Q(encerrado_em__isnull=False),
                name="chamado_encerrado",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(valor_previsto__gte=0) & Q(distancia_km__gte=0),
                name="chamado_valores_nao_negativos",
            ),
        ]

    def __str__(self) -> str:
        return f"Chamado #{self.pk} ({self.placa})"


class ItemValor(models.Model):
    chamado = models.ForeignKey(Chamado, on_delete=models.CASCADE, related_name="itens")
    tipo = models.CharField(max_length=20, choices=TipoItem.choices)
    descricao = models.CharField(max_length=120, blank=True)
    quantidade = models.DecimalField(max_digits=10, decimal_places=2)
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "item de valor"
        verbose_name_plural = "itens de valor"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantidade__gt=0) & Q(valor_unitario__gte=0),
                name="item_valor_positivo",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} — {self.total}"


class EventoChamado(models.Model):
    chamado = models.ForeignKey(
        Chamado, on_delete=models.CASCADE, related_name="eventos", db_index=False
    )
    # Nulo quando o evento vem do sistema (ex.: timeout de aceite).
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        db_index=False,
    )
    de_status = models.CharField(max_length=20, choices=Status.choices, null=True)
    para_status = models.CharField(max_length=20, choices=Status.choices)
    dados = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evento do chamado"
        verbose_name_plural = "eventos do chamado"
        indexes = [
            models.Index(fields=["chamado", "criado_em"], name="evento_chamado_criado"),
            BrinIndex(fields=["criado_em"], name="evento_criado_brin"),
        ]

    def __str__(self) -> str:
        return f"{self.de_status or '—'} → {self.para_status}"
