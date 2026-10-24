from collections.abc import Callable, Iterator

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.contas.models import Papel, Usuario
from config.celery import app as celery_app
from tests.factories import UsuarioFactory


@pytest.fixture(autouse=True, scope="session")
def _celery_em_memoria() -> None:
    """Tarefas enfileiradas em testes (ex.: on_commit do despacho) não vão para o Redis."""
    celery_app.conf.update(broker_url="memory://", task_always_eager=False)


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
