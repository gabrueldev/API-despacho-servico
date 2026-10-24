"""Última posição dos prestadores: escrita quente no Redis, gravação em lote no Postgres.

- `registrar`: 1 ida ao Redis (script Lua atômico), nenhuma ao Postgres.
- `gravar_pendentes`: a cada N segundos, um único `UPDATE ... FROM (VALUES ...)` por lote,
  só com quem se moveu (> ~1 m) desde o último envio.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from django.db import connection, transaction
from django_redis import get_redis_connection

from .models import Prestador

CHAVE_POSICAO = "loc:usuario:{}"
CHAVE_PENDENTES = "loc:pendentes"
TTL_POSICAO_SEGUNDOS = 24 * 60 * 60
CASAS = 5  # ~1,1 m: abaixo disso é ruído do GPS, não movimento
TAMANHO_LOTE = 1000

# Grava a posição e só marca como pendente se ela mudou.
_REGISTRAR = """
local antiga_lat = redis.call('HGET', KEYS[1], 'lat')
local antiga_lng = redis.call('HGET', KEYS[1], 'lng')
redis.call('HSET', KEYS[1], 'lat', ARGV[1], 'lng', ARGV[2], 'ts', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[5])
if antiga_lat ~= ARGV[1] or antiga_lng ~= ARGV[2] then
  redis.call('SADD', KEYS[2], ARGV[4])
  return 1
end
return 0
"""


def _redis() -> Any:
    return get_redis_connection("default")


def registrar(usuario_id: int, lat: float, lng: float) -> bool:
    """Devolve True se a posição mudou (e entrou na fila de gravação)."""
    agora = datetime.now(UTC).isoformat()
    script = _redis().register_script(_REGISTRAR)
    mudou = script(
        keys=[CHAVE_POSICAO.format(usuario_id), CHAVE_PENDENTES],
        args=[f"{lat:.{CASAS}f}", f"{lng:.{CASAS}f}", agora, usuario_id, TTL_POSICAO_SEGUNDOS],
    )
    return bool(mudou)


def ultima_posicao(usuario_id: int) -> dict[str, Any] | None:
    dados = _redis().hgetall(CHAVE_POSICAO.format(usuario_id))
    if not dados:
        return None
    return {
        "lat": float(dados[b"lat"]),
        "lng": float(dados[b"lng"]),
        "registrado_em": dados[b"ts"].decode(),
    }


def _lotes() -> Iterator[list[int]]:
    r = _redis()
    while ids := r.spop(CHAVE_PENDENTES, TAMANHO_LOTE):
        yield [int(i) for i in ids]


def _gravar_lote(usuario_ids: list[int]) -> int:
    r = _redis()
    pipe = r.pipeline(transaction=False)
    for uid in usuario_ids:
        pipe.hmget(CHAVE_POSICAO.format(uid), "lat", "lng", "ts")
    linhas = [
        (uid, float(lat), float(lng), ts.decode())
        for uid, (lat, lng, ts) in zip(usuario_ids, pipe.execute(), strict=True)
        if lat is not None
    ]
    if not linhas:
        return 0

    valores = ", ".join(["(%s::bigint, %s::float8, %s::float8, %s::timestamptz)"] * len(linhas))
    sql = f"""
        UPDATE {Prestador._meta.db_table} AS p
        SET localizacao = ST_SetSRID(ST_MakePoint(v.lng, v.lat), 4326)::geography,
            atualizado_em = v.ts
        FROM (VALUES {valores}) AS v(usuario_id, lat, lng, ts)
        WHERE p.usuario_id = v.usuario_id
    """  # noqa: S608 — só placeholders são interpolados
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql, [campo for linha in linhas for campo in linha])
        return int(cursor.rowcount)


def gravar_pendentes() -> int:
    """Esvazia a fila de pendentes em lotes. Se um lote falhar, ele volta para a fila."""
    total = 0
    for lote in _lotes():
        try:
            total += _gravar_lote(lote)
        except Exception:
            _redis().sadd(CHAVE_PENDENTES, *lote)
            raise
    return total
