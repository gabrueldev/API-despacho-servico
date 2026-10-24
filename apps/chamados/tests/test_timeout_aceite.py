from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.chamados import services, tasks
from apps.chamados.models import Chamado, EventoChamado, Status
from apps.contas.models import Papel
from core import tasks as core_tasks
from core.exceptions import Conflito
from tests.factories import ChamadoFactory, PrestadorFactory, UsuarioFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def despachante():
    return UsuarioFactory.create(papel=Papel.DESPACHANTE)


@pytest.fixture
def enfileiradas(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    """Captura o que seria enviado ao broker."""
    fila: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        tasks.expirar_aceite,
        "apply_async",
        lambda kwargs, countdown: fila.append(
            ("expirar_aceite", {**kwargs, "_countdown": countdown})
        ),
    )
    monkeypatch.setattr(
        core_tasks.notificar, "delay", lambda **kwargs: fila.append(("notificar", kwargs))
    )
    return fila


def _despachar(despachante, chamado: Chamado, prestador, capturar) -> Chamado:
    with capturar(execute=True):
        return services.despachar(
            usuario=despachante, chamado_id=chamado.pk, prestador_id=prestador.pk
        )


def test_despacho_agenda_timeout_e_notifica_apos_commit(
    despachante, enfileiradas, django_capture_on_commit_callbacks, settings
) -> None:
    chamado = ChamadoFactory.create()
    prestador = PrestadorFactory.create()

    _despachar(despachante, chamado, prestador, django_capture_on_commit_callbacks)

    assert enfileiradas == [
        (
            "expirar_aceite",
            {
                "chamado_id": chamado.pk,
                "version": 2,
                "prestador_id": prestador.pk,
                "_countdown": settings.ACEITE_TIMEOUT_SEGUNDOS,
            },
        ),
        (
            "notificar",
            {
                "usuario_id": prestador.usuario_id,
                "tipo": "chamado_despachado",
                "dados": {"chamado_id": chamado.pk},
                "chave": f"despachado:{chamado.pk}:2",
            },
        ),
    ]


def test_despacho_que_falha_nao_agenda_nada(
    despachante, enfileiradas, django_capture_on_commit_callbacks
) -> None:
    prestador = PrestadorFactory.create(disponivel=False)

    with pytest.raises(Conflito), django_capture_on_commit_callbacks(execute=True):
        services.despachar(
            usuario=despachante, chamado_id=ChamadoFactory.create().pk, prestador_id=prestador.pk
        )

    assert enfileiradas == []


def test_sem_aceite_volta_para_a_fila_e_libera_prestador(
    despachante, enfileiradas, django_capture_on_commit_callbacks
) -> None:
    chamado = ChamadoFactory.create()
    prestador = PrestadorFactory.create()
    _despachar(despachante, chamado, prestador, django_capture_on_commit_callbacks)

    assert tasks.expirar_aceite.apply(
        kwargs={"chamado_id": chamado.pk, "version": 2, "prestador_id": prestador.pk}
    ).get()

    chamado.refresh_from_db()
    prestador.refresh_from_db()
    assert (chamado.status, chamado.prestador_id, chamado.version) == (Status.ABERTO, None, 3)
    assert prestador.disponivel is True
    evento = EventoChamado.objects.filter(chamado=chamado).latest("id")
    assert (evento.usuario_id, evento.de_status, evento.para_status) == (
        None,
        "DESPACHADO",
        "ABERTO",
    )
    assert evento.dados == {"motivo": "timeout_aceite", "prestador_id": prestador.pk}


def test_timeout_nao_le_nada_do_banco(
    despachante, enfileiradas, django_capture_on_commit_callbacks
) -> None:
    chamado = ChamadoFactory.create()
    prestador = PrestadorFactory.create()
    _despachar(despachante, chamado, prestador, django_capture_on_commit_callbacks)

    with CaptureQueriesContext(connection) as ctx:
        services.expirar_aceite(chamado_id=chamado.pk, version=2, prestador_id=prestador.pk)

    sql = [q["sql"].split()[0] for q in ctx.captured_queries]
    assert "SELECT" not in sql
    assert sql.count("UPDATE") == 2 and sql.count("INSERT") == 1


def test_aceite_aos_1_59_vence_o_timeout(
    despachante, enfileiradas, django_capture_on_commit_callbacks
) -> None:
    chamado = ChamadoFactory.create()
    prestador = PrestadorFactory.create()
    _despachar(despachante, chamado, prestador, django_capture_on_commit_callbacks)
    services.aceitar(usuario=prestador.usuario, chamado_id=chamado.pk)

    expirou = services.expirar_aceite(chamado_id=chamado.pk, version=2, prestador_id=prestador.pk)

    assert expirou is False
    chamado.refresh_from_db()
    prestador.refresh_from_db()
    assert chamado.status == Status.ACEITO
    assert prestador.disponivel is False
    assert EventoChamado.objects.filter(chamado=chamado).count() == 2


def test_timeout_antigo_nao_desfaz_redespacho(
    despachante, enfileiradas, django_capture_on_commit_callbacks
) -> None:
    chamado = ChamadoFactory.create()
    primeiro, segundo = PrestadorFactory.create(), PrestadorFactory.create()
    _despachar(despachante, chamado, primeiro, django_capture_on_commit_callbacks)
    services.recusar(usuario=primeiro.usuario, chamado_id=chamado.pk)
    _despachar(despachante, chamado, segundo, django_capture_on_commit_callbacks)

    # O timeout do 1º despacho chega depois: não pode mexer no 2º.
    assert not services.expirar_aceite(chamado_id=chamado.pk, version=2, prestador_id=primeiro.pk)

    chamado.refresh_from_db()
    assert (chamado.status, chamado.prestador_id) == (Status.DESPACHADO, segundo.pk)


def test_timeout_reentregue_e_idempotente(
    despachante, enfileiradas, django_capture_on_commit_callbacks
) -> None:
    chamado = ChamadoFactory.create()
    prestador = PrestadorFactory.create()
    _despachar(despachante, chamado, prestador, django_capture_on_commit_callbacks)
    kwargs = {"chamado_id": chamado.pk, "version": 2, "prestador_id": prestador.pk}

    assert services.expirar_aceite(**kwargs) is True
    assert services.expirar_aceite(**kwargs) is False
    assert EventoChamado.objects.filter(chamado=chamado, para_status=Status.ABERTO).count() == 1
