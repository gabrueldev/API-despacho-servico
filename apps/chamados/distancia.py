"""Distância do chamado (origem → destino), que define o km excedente do valor previsto.

Duas implementações, escolhidas por `DISTANCIA_PROVEDOR`:

- `LinhaRetaPostGIS`: geodésica, uma query sem tocar em tabela;
- `RotaOSRM`: km por estrada no OSRM (serviço próprio, mapas do OpenStreetMap).

Abrir chamado nunca falha por causa do mapa. Se o OSRM cair, demorar mais que
`OSRM_TIMEOUT_SEGUNDOS` ou não achar rota, a distância é a linha reta × fator de correção, com
`fonte=ESTIMADA` para o financeiro saber que foi estimada. Uma falha de rede também pausa as
consultas por `ROTA_PAUSA_SEGUNDOS` (circuit breaker), para que um OSRM fora do ar não custe o
timeout inteiro em cada chamado aberto.
"""

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

import httpx
from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import connection

from .models import FonteDistancia

logger = logging.getLogger("despacha.distancia")

CENTAVO = Decimal("0.01")
# 3 casas ≈ 110 m: pedidos para o mesmo pátio/oficina reaproveitam a rota já calculada.
CHAVE_ROTA = "rota:v1:{:.3f},{:.3f}:{:.3f},{:.3f}"
CHAVE_PAUSA = "rota:pausa"


@dataclass(frozen=True, slots=True)
class Distancia:
    km: Decimal
    fonte: FonteDistancia


class CalculadoraDistancia(Protocol):
    def medir(self, origem: Point, destino: Point) -> Distancia: ...


def _km(metros: float) -> Decimal:
    return (Decimal(metros) / 1000).quantize(CENTAVO, rounding=ROUND_HALF_UP)


class LinhaRetaPostGIS:
    """Distância geodésica (elipsoide WGS84) via `ST_Distance` em geography."""

    def medir(self, origem: Point, destino: Point) -> Distancia:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT ST_Distance(ST_GeogFromText(%s), ST_GeogFromText(%s))",
                [origem.ewkt, destino.ewkt],
            )
            (metros,) = cursor.fetchone()
        return Distancia(_km(metros), FonteDistancia.LINHA_RETA)


class RotaIndisponivel(Exception):
    """Rede, timeout ou erro 5xx: o serviço está com problema, vale pausar."""


class SemRota(Exception):
    """O OSRM respondeu, mas não há rota (ponto no mar, fora do mapa): não é falha do serviço."""


# Um cliente por processo: reaproveita a conexão TCP (keep-alive) entre chamados. É criado na
# primeira consulta, depois do fork do Gunicorn/Celery, e é thread-safe (gthread).
_http: httpx.Client | None = None


def _cliente_http() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(limits=httpx.Limits(max_keepalive_connections=4))
    return _http


class RotaOSRM:
    def __init__(
        self,
        url: str,
        *,
        timeout: float,
        fator_estimativa: Decimal,
        plano_b: CalculadoraDistancia | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.fator_estimativa = fator_estimativa
        self.plano_b = plano_b or LinhaRetaPostGIS()

    def medir(self, origem: Point, destino: Point) -> Distancia:
        chave = CHAVE_ROTA.format(origem.y, origem.x, destino.y, destino.x)
        if (km := cache.get(chave)) is not None:
            return Distancia(Decimal(km), FonteDistancia.ROTA)
        if cache.get(CHAVE_PAUSA):
            return self._estimar(origem, destino)

        try:
            metros = self._consultar(origem, destino)
        except RotaIndisponivel as erro:
            logger.warning("OSRM indisponível, pausando consultas: %s", erro)
            cache.set(CHAVE_PAUSA, 1, settings.ROTA_PAUSA_SEGUNDOS)
            return self._estimar(origem, destino)
        except SemRota as erro:
            logger.info("Sem rota entre %s e %s: %s", origem.coords, destino.coords, erro)
            return self._estimar(origem, destino)

        km = _km(metros)
        cache.set(chave, str(km), settings.ROTA_CACHE_DIAS * 86_400)
        return Distancia(km, FonteDistancia.ROTA)

    def _consultar(self, origem: Point, destino: Point) -> float:
        # OSRM recebe lng,lat. Sem geometria nem passos: só a distância, resposta mínima.
        url = (
            f"{self.url}/route/v1/driving/"
            f"{origem.x:.6f},{origem.y:.6f};{destino.x:.6f},{destino.y:.6f}"
        )
        params = {"overview": "false", "alternatives": "false", "steps": "false"}
        try:
            resposta = _cliente_http().get(url, params=params, timeout=self.timeout)
        except httpx.HTTPError as erro:  # timeout, conexão recusada, DNS…
            raise RotaIndisponivel(repr(erro)) from erro
        if resposta.status_code >= 500:
            raise RotaIndisponivel(f"HTTP {resposta.status_code}")

        try:
            corpo: dict[str, Any] = resposta.json()
        except ValueError as erro:
            raise RotaIndisponivel("resposta não é JSON") from erro
        if corpo.get("code") != "Ok" or not corpo.get("routes"):
            raise SemRota(corpo.get("code") or f"HTTP {resposta.status_code}")
        return float(corpo["routes"][0]["distance"])

    def _estimar(self, origem: Point, destino: Point) -> Distancia:
        reta = self.plano_b.medir(origem, destino)
        km = (reta.km * self.fator_estimativa).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        return Distancia(km, FonteDistancia.ESTIMADA)


def obter_calculadora() -> CalculadoraDistancia:
    """Lida a cada chamada (barata): `settings` pode mudar em testes sem reiniciar nada."""
    provedor = settings.DISTANCIA_PROVEDOR
    if provedor == "linha_reta":
        return LinhaRetaPostGIS()
    if provedor == "osrm":
        return RotaOSRM(
            settings.OSRM_URL,
            timeout=settings.OSRM_TIMEOUT_SEGUNDOS,
            fator_estimativa=Decimal(str(settings.DISTANCIA_FATOR_ESTIMATIVA)),
        )
    raise ImproperlyConfigured(f"DISTANCIA_PROVEDOR inválido: {provedor!r} (linha_reta | osrm)")


def medir(origem: Point, destino: Point) -> Distancia:
    return obter_calculadora().medir(origem, destino)
