from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import GistIndex
from django.db.models import Q


class Prestador(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="prestador"
    )
    nome = models.CharField(max_length=160)
    telefone = models.CharField(max_length=20)
    disponivel = models.BooleanField(default=False)
    # Sem o índice espacial padrão: o GiST parcial abaixo cobre a busca por proximidade.
    localizacao = models.PointField(geography=True, srid=4326, null=True, spatial_index=False)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "prestadores"
        indexes = [
            GistIndex(
                fields=["localizacao"],
                condition=Q(disponivel=True),
                name="prestador_livre_loc_gist",
            ),
        ]

    def __str__(self) -> str:
        return self.nome
