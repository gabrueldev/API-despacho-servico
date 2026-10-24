from django.db import models

from apps.precos.models import TabelaPrecos


class Cliente(models.Model):
    """Contratante (ex.: proteção veicular)."""

    nome = models.CharField(max_length=160)
    cnpj = models.CharField(max_length=14, unique=True)
    tabela_precos = models.ForeignKey(TabelaPrecos, on_delete=models.PROTECT, related_name="+")
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cnpj__regex=r"^\d{14}$"), name="cnpj_14_digitos"
            ),
        ]

    def __str__(self) -> str:
        return self.nome
