from django.conf import settings
from django.contrib.postgres.indexes import BrinIndex
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class IdempotencyKey(models.Model):
    # Sem índice próprio: a constraint única (usuario, chave) já começa por usuario.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+", db_index=False
    )
    chave = models.CharField(max_length=255)
    hash_requisicao = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    resposta = models.JSONField(encoder=DjangoJSONEncoder)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["usuario", "chave"], name="idempotency_usuario_chave"),
        ]
        indexes = [BrinIndex(fields=["criado_em"], name="idempotency_criado_brin")]

    def __str__(self) -> str:
        return self.chave
