"""Erros de domínio e formato único de resposta de erro.

Services levantam `ErroDominio` (sem depender do DRF); o handler traduz para HTTP.
Corpo padrão: {"erro": "<codigo>", "detalhe": <mensagem ou campos>}.
"""

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class ErroDominio(Exception):
    codigo = "regra_de_negocio"
    status_http: int = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(self, detalhe: str, codigo: str | None = None) -> None:
        super().__init__(detalhe)
        self.detalhe = detalhe
        if codigo:
            self.codigo = codigo


class NaoEncontrado(ErroDominio):
    codigo = "nao_encontrado"
    status_http = status.HTTP_404_NOT_FOUND


class Conflito(ErroDominio):
    codigo = "conflito"
    status_http = status.HTTP_409_CONFLICT


_CODIGOS_DRF: dict[type[Exception], str] = {
    Http404: "nao_encontrado",
    DjangoPermissionDenied: "sem_permissao",
    exceptions.ValidationError: "validacao",
    exceptions.NotAuthenticated: "nao_autenticado",
    exceptions.AuthenticationFailed: "nao_autenticado",
    exceptions.PermissionDenied: "sem_permissao",
    exceptions.NotFound: "nao_encontrado",
    exceptions.Throttled: "limite_excedido",
}


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, ErroDominio):
        return Response({"erro": exc.codigo, "detalhe": exc.detalhe}, status=exc.status_http)

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    codigo = next((c for tipo, c in _CODIGOS_DRF.items() if isinstance(exc, tipo)), "erro")
    data = response.data
    detalhe = data.get("detail", data) if isinstance(data, dict) else data
    response.data = {"erro": codigo, "detalhe": detalhe}
    return response
