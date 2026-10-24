from collections.abc import Callable, Iterator

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.contas.models import Papel, Usuario
from tests.factories import UsuarioFactory


@pytest.fixture(autouse=True)
def _cache_limpo() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def cliente_api() -> Callable[..., APIClient]:
    """`cliente_api(Papel.ATENDENTE)` -> APIClient autenticado (sem query de JWT por request)."""

    def _criar(papel: Papel = Papel.ATENDENTE, usuario: Usuario | None = None) -> APIClient:
        client = APIClient()
        client.force_authenticate(usuario or UsuarioFactory(papel=papel))
        return client

    return _criar
