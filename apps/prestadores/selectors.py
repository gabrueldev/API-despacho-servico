from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.conf import settings
from django.db import connection
from django.utils import timezone

from .models import Prestador


@dataclass(frozen=True, slots=True)
class PrestadorProximo:
    id: int
    nome: str
    telefone: str
    lat: float
    lng: float
    distancia_km: Decimal


# SQL explícito porque o ORM ordena por `ST_Distance` (calcula para todo candidato e ordena
# em memória). Aqui:
# - `ST_DWithin` filtra o raio usando o GiST parcial `prestador_livre_loc_gist`;
# - `<->` (KNN) faz o próprio índice devolver os mais próximos já em ordem, parando no LIMIT;
# - o ponto entra como expressão constante (não via JOIN), condição para o KNN usar índice.
# O `<->` em geography mede na esfera; a distância exibida (`ST_Distance`) é no elipsoide.
# A diferença (~0,3%) só poderia inverter dois prestadores praticamente equidistantes.
_PONTO = "ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography"
_SQL_PROXIMOS = f"""
    SELECT p.id, p.nome, p.telefone,
           ST_Y(p.localizacao::geometry), ST_X(p.localizacao::geometry),
           ST_Distance(p.localizacao, {_PONTO})
    FROM {Prestador._meta.db_table} AS p
    WHERE p.disponivel
      AND p.atualizado_em >= %(desde)s
      AND ST_DWithin(p.localizacao, {_PONTO}, %(raio_m)s)
    ORDER BY p.localizacao <-> {_PONTO}
    LIMIT %(limite)s
"""  # noqa: S608 — só placeholders são interpolados


def proximos(
    *, lat: float, lng: float, raio_km: float, limite: int | None = None
) -> list[PrestadorProximo]:
    """Prestadores disponíveis no raio, do mais próximo ao mais distante. Uma query."""
    params: dict[str, Any] = {
        "lat": lat,
        "lng": lng,
        "raio_m": raio_km * 1000,
        "desde": timezone.now() - timedelta(minutes=settings.POSICAO_VALIDADE_MINUTOS),
        "limite": limite or settings.PROXIMOS_LIMITE,
    }
    with connection.cursor() as cursor:
        cursor.execute(_SQL_PROXIMOS, params)
        linhas = cursor.fetchall()
    return [
        PrestadorProximo(
            id=pid,
            nome=nome,
            telefone=telefone,
            lat=plat,
            lng=plng,
            distancia_km=(Decimal(metros) / 1000).quantize(Decimal("0.01"), ROUND_HALF_UP),
        )
        for pid, nome, telefone, plat, plng, metros in linhas
    ]
