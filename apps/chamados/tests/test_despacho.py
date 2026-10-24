import threading
import time

import pytest
from django.db import connection, transaction
from django.urls import reverse

from apps.chamados import services
from apps.chamados.models import Chamado, EventoChamado, Status
from apps.contas.models import Papel
from apps.prestadores.models import Prestador
from core.exceptions import Conflito
from tests.concorrencia import em_paralelo
from tests.factories import ChamadoFactory, PrestadorFactory, UsuarioFactory


def _url(chamado: Chamado) -> str:
    return reverse("chamado-despachar", args=[chamado.pk])


# --- regras (banco normal, transação por teste) -------------------------------------------------


@pytest.mark.django_db
def test_despachar_reserva_prestador_e_registra_evento(cliente_api) -> None:
    chamado = ChamadoFactory.create()
    prestador = PrestadorFactory.create()

    response = cliente_api(Papel.DESPACHANTE).post(
        _url(chamado), {"prestador_id": prestador.pk}, format="json"
    )

    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "DESPACHADO"
    chamado.refresh_from_db()
    prestador.refresh_from_db()
    assert chamado.prestador_id == prestador.pk
    assert prestador.disponivel is False
    evento = EventoChamado.objects.get(chamado=chamado)
    assert (evento.para_status, evento.dados) == ("DESPACHADO", {"prestador_id": prestador.pk})


@pytest.mark.django_db
def test_despachar_numero_de_queries(cliente_api, django_assert_num_queries) -> None:
    chamado = ChamadoFactory.create()
    prestador = PrestadorFactory.create()
    client = cliente_api(Papel.DESPACHANTE)

    # SAVEPOINT, SELECT chamado FOR UPDATE NOWAIT, SELECT prestador FOR UPDATE NOWAIT,
    # UPDATE chamado (version), INSERT evento, UPDATE prestador, RELEASE SAVEPOINT
    with django_assert_num_queries(7):
        response = client.post(_url(chamado), {"prestador_id": prestador.pk}, format="json")
    assert response.status_code == 200


@pytest.mark.django_db
def test_segundo_despacho_do_mesmo_chamado_recebe_409(cliente_api) -> None:
    chamado = ChamadoFactory.create()
    client = cliente_api(Papel.DESPACHANTE)
    client.post(_url(chamado), {"prestador_id": PrestadorFactory.create().pk}, format="json")

    response = client.post(
        _url(chamado), {"prestador_id": PrestadorFactory.create().pk}, format="json"
    )

    assert response.status_code == 409
    assert response.json()["erro"] == "conflito"


@pytest.mark.django_db
def test_prestador_indisponivel_recebe_409(cliente_api) -> None:
    prestador = PrestadorFactory.create(disponivel=False)

    response = cliente_api(Papel.DESPACHANTE).post(
        _url(ChamadoFactory.create()), {"prestador_id": prestador.pk}, format="json"
    )

    assert response.status_code == 409
    assert response.json()["erro"] == "prestador_indisponivel"


@pytest.mark.django_db
def test_chamado_ou_prestador_inexistente_recebe_404(cliente_api) -> None:
    client = cliente_api(Papel.DESPACHANTE)
    chamado = ChamadoFactory.create()

    sem_prestador = client.post(_url(chamado), {"prestador_id": 999_999}, format="json")
    sem_chamado = client.post(
        reverse("chamado-despachar", args=[999_999]),
        {"prestador_id": PrestadorFactory.create().pk},
        format="json",
    )

    assert (sem_prestador.status_code, sem_chamado.status_code) == (404, 404)
    chamado.refresh_from_db()
    assert chamado.status == Status.ABERTO


@pytest.mark.django_db
@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.PRESTADOR, Papel.FINANCEIRO])
def test_so_despachante_despacha(cliente_api, papel) -> None:
    response = cliente_api(papel).post(
        _url(ChamadoFactory.create()), {"prestador_id": PrestadorFactory.create().pk}, format="json"
    )

    assert response.status_code == 403


# --- concorrência real (threads + conexões independentes) ---------------------------------------


@pytest.mark.django_db(transaction=True)
def test_nowait_responde_409_na_hora_sem_esperar_a_trava() -> None:
    chamado = ChamadoFactory.create()
    prestador = PrestadorFactory.create()
    despachante = UsuarioFactory.create(papel=Papel.DESPACHANTE)
    travado, liberar = threading.Event(), threading.Event()

    def segura_a_linha() -> None:
        try:
            with transaction.atomic():
                Chamado.objects.select_for_update().get(pk=chamado.pk)
                travado.set()
                liberar.wait(timeout=10)
        finally:
            connection.close()

    outra = threading.Thread(target=segura_a_linha)
    outra.start()
    assert travado.wait(timeout=5)
    try:
        inicio = time.monotonic()
        with pytest.raises(Conflito):
            services.despachar(
                usuario=despachante, chamado_id=chamado.pk, prestador_id=prestador.pk
            )
        assert time.monotonic() - inicio < 0.5  # não ficou esperando a outra transação
    finally:
        liberar.set()
        outra.join()

    assert Chamado.objects.get(pk=chamado.pk).status == Status.ABERTO


@pytest.mark.django_db(transaction=True)
def test_varios_despachantes_ao_mesmo_tempo_so_um_vence() -> None:
    n = 8
    chamado = ChamadoFactory.create()
    prestadores = [PrestadorFactory.create() for _ in range(n)]
    despachantes = [UsuarioFactory.create(papel=Papel.DESPACHANTE) for _ in range(n)]

    resultados = em_paralelo(
        n,
        lambda i: services.despachar(
            usuario=despachantes[i], chamado_id=chamado.pk, prestador_id=prestadores[i].pk
        ),
    )

    vencedores = [i for i, r in enumerate(resultados) if isinstance(r, Chamado)]
    assert len(vencedores) == 1, resultados
    assert all(isinstance(r, Conflito) for i, r in enumerate(resultados) if i not in vencedores)

    chamado.refresh_from_db()
    vencedor = prestadores[vencedores[0]]
    assert (chamado.status, chamado.prestador_id, chamado.version) == (
        Status.DESPACHADO,
        vencedor.pk,
        2,
    )
    assert EventoChamado.objects.filter(chamado=chamado).count() == 1
    ocupados = set(Prestador.objects.filter(disponivel=False).values_list("pk", flat=True))
    assert ocupados == {vencedor.pk}


@pytest.mark.django_db(transaction=True)
def test_mesmo_prestador_em_dois_chamados_ao_mesmo_tempo() -> None:
    chamados = [ChamadoFactory.create(), ChamadoFactory.create()]
    prestador = PrestadorFactory.create()
    despachantes = [UsuarioFactory.create(papel=Papel.DESPACHANTE) for _ in range(2)]

    resultados = em_paralelo(
        2,
        lambda i: services.despachar(
            usuario=despachantes[i], chamado_id=chamados[i].pk, prestador_id=prestador.pk
        ),
    )

    assert sum(isinstance(r, Chamado) for r in resultados) == 1, resultados
    assert sum(isinstance(r, Conflito) for r in resultados) == 1
    status = sorted(Chamado.objects.values_list("status", flat=True))
    assert status == [Status.ABERTO, Status.DESPACHADO]
