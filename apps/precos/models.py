from decimal import Decimal

from django.db import models
from django.db.models import Q

from .calculo import Tabela


class TabelaPrecos(models.Model):
    nome = models.CharField(max_length=120)
    valor_saida = models.DecimalField(max_digits=10, decimal_places=2)
    valor_km_excedente = models.DecimalField(max_digits=10, decimal_places=2)
    km_franquia = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(40))
    valor_hora_espera = models.DecimalField(max_digits=10, decimal_places=2)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "tabela de preços"
        verbose_name_plural = "tabelas de preços"
        constraints = [
            models.CheckConstraint(
                condition=Q(valor_saida__gte=0)
                & Q(valor_km_excedente__gte=0)
                & Q(km_franquia__gte=0)
                & Q(valor_hora_espera__gte=0),
                name="tabela_precos_valores_nao_negativos",
            ),
        ]

    def __str__(self) -> str:
        return self.nome

    def dados(self) -> Tabela:
        return Tabela(
            valor_saida=self.valor_saida,
            valor_km_excedente=self.valor_km_excedente,
            km_franquia=self.km_franquia,
            valor_hora_espera=self.valor_hora_espera,
        )
