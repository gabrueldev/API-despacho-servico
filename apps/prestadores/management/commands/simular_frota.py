"""`python manage.py simular_frota`: mantém a frota de demonstração "viva".

A busca por proximidade só considera quem mandou posição nos últimos
`POSICAO_VALIDADE_MINUTOS`; sem isto, minutos depois do `seed` o mapa do despachante fica
vazio. Cada rodada move os prestadores disponíveis alguns metros, pelo mesmo caminho da API
(`localizacao.registrar` no Redis), e grava em lote (`gravar_pendentes`) sem depender do Beat.
"""

import math
import random
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.prestadores import localizacao
from apps.prestadores.models import Prestador

METROS_POR_GRAU = 111_320


def passo(lat: float, lng: float, metros: float, rumo_graus: float) -> tuple[float, float]:
    """Desloca `metros` no rumo dado (0 = norte). Aproximação plana: ótima para centenas de m."""
    rumo = math.radians(rumo_graus)
    dlat = metros * math.cos(rumo) / METROS_POR_GRAU
    dlng = metros * math.sin(rumo) / (METROS_POR_GRAU * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng


class Command(BaseCommand):
    help = "Move os prestadores disponíveis periodicamente (dados de demonstração)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--intervalo", type=float, default=20, help="Segundos entre rodadas.")
        parser.add_argument(
            "--passo", type=float, default=150, help="Metros por rodada, no máximo."
        )
        parser.add_argument("--rodadas", type=int, default=0, help="0 = sem fim.")

    def handle(self, *args: Any, **opcoes: Any) -> None:
        if opcoes["intervalo"] <= 0 or opcoes["passo"] <= 0:
            raise CommandError("Use --intervalo e --passo positivos.")
        rng = random.Random(42)  # noqa: S311 — movimento de demonstração, não segredo
        rodada = 0
        while True:
            rodada += 1
            movidos, gravados = self._rodada(rng, opcoes["passo"])
            self.stdout.write(
                f"Rodada {rodada}: {movidos} prestadores movidos, {gravados} gravados."
            )
            if rodada == opcoes["rodadas"]:
                return
            time.sleep(opcoes["intervalo"])

    def _rodada(self, rng: random.Random, passo_maximo: float) -> tuple[int, int]:
        frota = Prestador.objects.filter(disponivel=True, localizacao__isnull=False).values_list(
            "usuario_id", "localizacao"
        )
        movidos = 0
        for usuario_id, ponto in frota.iterator(chunk_size=1000):
            atual = localizacao.ultima_posicao(usuario_id)
            # `ponto` nunca é None: a query filtra localizacao__isnull=False.
            lat, lng = (atual["lat"], atual["lng"]) if atual else (ponto.y, ponto.x)  # type: ignore[union-attr]
            lat, lng = passo(lat, lng, rng.uniform(0.3, 1) * passo_maximo, rng.uniform(0, 360))
            movidos += localizacao.registrar(usuario_id, lat, lng)
        return movidos, localizacao.gravar_pendentes()
