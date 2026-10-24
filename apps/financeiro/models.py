from django.db import models
from django.db.models import Q

from apps.chamados.models import Chamado
from apps.clientes.models import Cliente
from apps.prestadores.models import Prestador


class TipoFechamento(models.TextChoices):
    CLIENTE = "CLIENTE", "Cliente (a cobrar)"
    PRESTADOR = "PRESTADOR", "Prestador (a repassar)"


class StatusFechamento(models.TextChoices):
    GERADO = "GERADO", "Gerado"
    PAGO = "PAGO", "Pago"


class Fechamento(models.Model):
    tipo = models.CharField(max_length=10, choices=TipoFechamento.choices)
    # FKs reais (não um referencia_id genérico): integridade, JOIN e índice.
    # Sem índice próprio: as constraints únicas abaixo já começam por elas.
    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, null=True, related_name="+", db_index=False
    )
    prestador = models.ForeignKey(
        Prestador, on_delete=models.PROTECT, null=True, related_name="+", db_index=False
    )
    periodo_inicio = models.DateField()
    periodo_fim = models.DateField()
    total = models.DecimalField(max_digits=14, decimal_places=2)
    quantidade_chamados = models.PositiveIntegerField()
    status = models.CharField(
        max_length=10, choices=StatusFechamento.choices, default=StatusFechamento.GERADO
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(tipo=TipoFechamento.CLIENTE, cliente__isnull=False, prestador__isnull=True)
                    | Q(
                        tipo=TipoFechamento.PRESTADOR,
                        prestador__isnull=False,
                        cliente__isnull=True,
                    )
                ),
                name="fechamento_um_destinatario",
            ),
            # Idempotência da geração: um fechamento por destinatário e período.
            models.UniqueConstraint(
                fields=["cliente", "periodo_inicio"],
                condition=Q(tipo=TipoFechamento.CLIENTE),
                name="fechamento_cliente_periodo",
            ),
            models.UniqueConstraint(
                fields=["prestador", "periodo_inicio"],
                condition=Q(tipo=TipoFechamento.PRESTADOR),
                name="fechamento_prestador_periodo",
            ),
        ]
        indexes = [
            models.Index(fields=["periodo_inicio", "tipo"], name="fechamento_periodo_tipo"),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} {self.periodo_inicio:%m/%Y}"


class FechamentoItem(models.Model):
    # Sem índice próprio: a constraint única (fechamento, chamado) já começa por ela.
    fechamento = models.ForeignKey(
        Fechamento, on_delete=models.CASCADE, related_name="itens", db_index=False
    )
    chamado = models.ForeignKey(Chamado, on_delete=models.PROTECT, related_name="+", db_index=False)
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "item do fechamento"
        verbose_name_plural = "itens do fechamento"
        constraints = [
            models.UniqueConstraint(fields=["fechamento", "chamado"], name="fechamento_item_unico"),
        ]

    def __str__(self) -> str:
        return f"Chamado #{self.chamado_id}: {self.valor}"
