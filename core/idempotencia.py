"""Idempotência por header `Idempotency-Key` (escopo: usuário + chave).

- Chave nova: executa e grava a resposta **na mesma transação** da operação.
- Chave repetida com o mesmo corpo: devolve a resposta gravada, sem executar de novo.
- Chave repetida com corpo diferente: 422.
- Duas requisições simultâneas com a mesma chave: a segunda esbarra na constraint única,
  a operação dela é desfeita inteira e ela devolve a resposta da primeira.
- Só sucesso é gravado: um erro (ex.: 422 de regra) pode ser corrigido e reenviado.
- `preparar` (opcional) roda só para chave nova e **fora** da transação: o lugar de leituras
  lentas, como uma chamada HTTP, que não devem segurar transação aberta nem ser pagas por
  um reenvio.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.contas.models import Usuario

from .exceptions import ErroDominio
from .models import IdempotencyKey

TAMANHO_MAXIMO_CHAVE = 255


@dataclass(frozen=True, slots=True)
class Resultado:
    status_code: int
    corpo: Any
    repetido: bool = False


def hash_requisicao(dados: Any) -> str:
    canonico = json.dumps(dados, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonico.encode()).hexdigest()


def _buscar_valida(usuario: Usuario, chave: str) -> IdempotencyKey | None:
    registro = IdempotencyKey.objects.filter(usuario=usuario, chave=chave).first()
    if registro is None:
        return None
    validade = timedelta(hours=settings.IDEMPOTENCY_TTL_HORAS)
    if registro.criado_em < timezone.now() - validade:
        registro.delete()  # expirada: libera a chave para reuso
        return None
    return registro


def _repetir(registro: IdempotencyKey, hash_atual: str) -> Resultado:
    if registro.hash_requisicao != hash_atual:
        raise ErroDominio(
            "Esta Idempotency-Key já foi usada com outro corpo de requisição.",
            codigo="idempotency_key_reutilizada",
        )
    return Resultado(registro.status_code, registro.resposta, repetido=True)


def executar(
    *,
    usuario: Usuario,
    chave: str,
    dados: Any,
    operacao: Callable[[], Resultado],
    preparar: Callable[[], None] | None = None,
) -> Resultado:
    if not chave or len(chave) > TAMANHO_MAXIMO_CHAVE:
        raise ErroDominio(
            f"Idempotency-Key deve ter de 1 a {TAMANHO_MAXIMO_CHAVE} caracteres.",
            codigo="idempotency_key_invalida",
        )
    hash_atual = hash_requisicao(dados)

    if registro := _buscar_valida(usuario, chave):
        return _repetir(registro, hash_atual)

    if preparar:
        preparar()
    try:
        with transaction.atomic():
            resultado = operacao()
            IdempotencyKey.objects.create(
                usuario=usuario,
                chave=chave,
                hash_requisicao=hash_atual,
                status_code=resultado.status_code,
                resposta=resultado.corpo,
            )
    except IntegrityError:
        # Outra requisição com a mesma chave commitou primeiro; a nossa foi desfeita.
        if registro := _buscar_valida(usuario, chave):
            return _repetir(registro, hash_atual)
        raise
    return resultado
