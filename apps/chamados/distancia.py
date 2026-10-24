from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from django.contrib.gis.geos import Point
from django.db import connection


class CalculadoraDistancia(Protocol):
    def distancia_km(self, origem: Point, destino: Point) -> Decimal: ...


class LinhaRetaPostGIS:
    """Distância geodésica (elipsoide WGS84) via `ST_Distance` em geography.

    Uma query sem tocar em tabela. Rota real por estrada entra como outra implementação.
    """

    def distancia_km(self, origem: Point, destino: Point) -> Decimal:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT ST_Distance(ST_GeogFromText(%s), ST_GeogFromText(%s))",
                [origem.ewkt, destino.ewkt],
            )
            (metros,) = cursor.fetchone()
        return (Decimal(metros) / 1000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


calculadora_padrao: CalculadoraDistancia = LinhaRetaPostGIS()
