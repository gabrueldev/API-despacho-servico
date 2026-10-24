from decimal import Decimal

import pytest
from django.urls import reverse

from apps.chamados import services
from apps.chamados.models import Chamado, EventoChamado, ItemValor, Status
from apps.contas.models import Papel
from apps.precos.tipos import TipoItem
from core.exceptions import Conflito, ErroDominio
from tests.factories import ChamadoFactory, PrestadorFactory, UsuarioFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def prestador():
    return PrestadorFactory(disponivel=False)


def _no_status(status: Status, prestador=None) -> Chamado:
    return ChamadoFactory.create(status=status, prestador=prestador)


def _url(nome: str, chamado: Chamado) -> str:
    return reverse(f"chamado-{nome}", args=[chamado.pk])


def _eventos(chamado: Chamado) -> list[tuple[str | None, str]]:
    return list(
        EventoChamado.objects.filter(chamado=chamado)
        .order_by("criado_em", "id")
        .values_list("de_status", "para_status")
    )


# --- transicionar --------------------------------------------------------------------------------


def test_transicao_grava_status_version_e_evento() -> None:
    chamado = _no_status(Status.DESPACHADO)
    usuario = UsuarioFactory()

    services.transicionar(chamado, Status.ACEITO, usuario=usuario, dados={"x": 1})

    chamado.refresh_from_db()
    assert (chamado.status, chamado.version) == (Status.ACEITO, 2)
    evento = EventoChamado.objects.get(chamado=chamado)
    assert (evento.de_status, evento.para_status, evento.dados) == (
        "DESPACHADO",
        "ACEITO",
        {"x": 1},
    )
    assert evento.usuario_id == usuario.pk


def test_transicao_invalida_nao_grava_nada() -> None:
    chamado = _no_status(Status.ABERTO)

    with pytest.raises(ErroDominio) as erro:
        services.transicionar(chamado, Status.CONCLUIDO, usuario=None)

    assert erro.value.codigo == "transicao_invalida"
    chamado.refresh_from_db()
    assert (chamado.status, chamado.version) == (Status.ABERTO, 1)
    assert not EventoChamado.objects.exists()


def test_version_desatualizada_vira_conflito_sem_gravar() -> None:
    lido = _no_status(Status.DESPACHADO)
    # Outra operação passou na frente depois da leitura.
    Chamado.objects.filter(pk=lido.pk).update(version=2)

    with pytest.raises(Conflito):
        services.transicionar(lido, Status.ACEITO, usuario=None)

    assert Chamado.objects.get(pk=lido.pk).status == Status.DESPACHADO
    assert not EventoChamado.objects.exists()


# --- fluxo completo pela API ---------------------------------------------------------------------


def test_fluxo_completo_ate_concluir(cliente_api, prestador) -> None:
    chamado = _no_status(Status.DESPACHADO, prestador)
    ItemValor.objects.create(
        chamado=chamado,
        tipo=TipoItem.SAIDA,
        quantidade=1,
        valor_unitario=Decimal("250.00"),
        total=Decimal("250.00"),
    )
    ItemValor.objects.create(
        chamado=chamado,
        tipo=TipoItem.PEDAGIO,
        quantidade=1,
        valor_unitario=Decimal("12.40"),
        total=Decimal("12.40"),
    )
    client = cliente_api(usuario=prestador.usuario)

    assert client.post(_url("aceitar", chamado)).json()["status"] == "ACEITO"
    for status in ("A_CAMINHO", "NO_LOCAL", "EM_ATENDIMENTO"):
        response = client.post(_url("status", chamado), {"status": status}, format="json")
        assert response.status_code == 200, response.json()
    response = client.post(_url("concluir", chamado))

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "CONCLUIDO"
    assert body["valor_final"] == "262.40"
    assert body["version"] == 6
    assert body["encerrado_em"] is not None
    chamado.refresh_from_db()
    assert chamado.encerrado_em and chamado.rastreio_expira_em
    assert chamado.rastreio_expira_em > chamado.encerrado_em
    assert _eventos(chamado) == [
        ("DESPACHADO", "ACEITO"),
        ("ACEITO", "A_CAMINHO"),
        ("A_CAMINHO", "NO_LOCAL"),
        ("NO_LOCAL", "EM_ATENDIMENTO"),
        ("EM_ATENDIMENTO", "CONCLUIDO"),
    ]
    prestador.refresh_from_db()
    assert prestador.disponivel is True


def test_aceitar_usa_3_queries(cliente_api, prestador, django_assert_num_queries) -> None:
    chamado = _no_status(Status.DESPACHADO, prestador)
    client = cliente_api(usuario=prestador.usuario)

    # SELECT do chamado (colunas de estado), UPDATE condicional, INSERT do evento
    with django_assert_num_queries(3):
        response = client.post(_url("aceitar", chamado))
    assert response.status_code == 200


def test_pular_etapa_retorna_422(cliente_api, prestador) -> None:
    chamado = _no_status(Status.ACEITO, prestador)

    response = cliente_api(usuario=prestador.usuario).post(
        _url("status", chamado), {"status": "EM_ATENDIMENTO"}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["erro"] == "transicao_invalida"


def test_status_fora_dos_avancos_do_prestador_retorna_400(cliente_api, prestador) -> None:
    chamado = _no_status(Status.EM_ATENDIMENTO, prestador)

    response = cliente_api(usuario=prestador.usuario).post(
        _url("status", chamado), {"status": "CONCLUIDO"}, format="json"
    )

    assert response.status_code == 400


def test_recusar_devolve_para_fila_e_libera_prestador(cliente_api, prestador) -> None:
    chamado = _no_status(Status.DESPACHADO, prestador)

    response = cliente_api(usuario=prestador.usuario).post(
        _url("recusar", chamado), {"motivo": "pneu furado"}, format="json"
    )

    assert response.status_code == 200
    chamado.refresh_from_db()
    prestador.refresh_from_db()
    assert (chamado.status, chamado.prestador_id) == (Status.ABERTO, None)
    assert prestador.disponivel is True
    evento = EventoChamado.objects.get(chamado=chamado)
    assert evento.dados == {"prestador_id": prestador.pk, "motivo": "pneu furado"}


# --- cancelamento --------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [Status.ABERTO, Status.DESPACHADO, Status.ACEITO])
def test_cancelar_antes_do_deslocamento_nao_cobra(cliente_api, prestador, status) -> None:
    chamado = _no_status(status, None if status == Status.ABERTO else prestador)

    response = cliente_api(Papel.ATENDENTE).post(
        _url("cancelar", chamado), {"motivo": "cliente desistiu"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["valor_final"] == "0.00"
    assert not ItemValor.objects.filter(chamado=chamado, tipo=TipoItem.TAXA_CANCELAMENTO).exists()


@pytest.mark.parametrize("status", [Status.A_CAMINHO, Status.NO_LOCAL, Status.EM_ATENDIMENTO])
def test_cancelar_apos_deslocamento_cobra_taxa_de_saida(cliente_api, prestador, status) -> None:
    chamado = _no_status(status, prestador)

    response = cliente_api(Papel.DESPACHANTE).post(
        _url("cancelar", chamado), {"motivo": "resolvido no local"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["valor_final"] == "250.00"
    taxa = ItemValor.objects.get(chamado=chamado, tipo=TipoItem.TAXA_CANCELAMENTO)
    assert taxa.total == Decimal("250.00")
    chamado.refresh_from_db()
    prestador.refresh_from_db()
    assert chamado.encerrado_em is not None
    assert chamado.rastreio_expira_em == chamado.encerrado_em
    assert prestador.disponivel is True


@pytest.mark.parametrize("status", [Status.CONCLUIDO, Status.CANCELADO])
def test_encerrado_nao_cancela(cliente_api, status) -> None:
    chamado = _no_status(status)

    response = cliente_api(Papel.ATENDENTE).post(
        _url("cancelar", chamado), {"motivo": "x"}, format="json"
    )

    assert response.status_code == 422


def test_cancelar_exige_motivo(cliente_api) -> None:
    response = cliente_api(Papel.ATENDENTE).post(_url("cancelar", _no_status(Status.ABERTO)))

    assert response.status_code == 400
    assert "motivo" in response.json()["detalhe"]


# --- permissões ----------------------------------------------------------------------------------


@pytest.mark.parametrize("acao", ["aceitar", "recusar", "concluir"])
def test_prestador_de_outro_chamado_recebe_404(cliente_api, prestador, acao) -> None:
    chamado = _no_status(Status.DESPACHADO, PrestadorFactory())

    response = cliente_api(usuario=prestador.usuario).post(_url(acao, chamado))

    assert response.status_code == 404


@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.DESPACHANTE, Papel.FINANCEIRO])
def test_so_prestador_aceita(cliente_api, papel) -> None:
    chamado = _no_status(Status.DESPACHADO, PrestadorFactory())

    assert cliente_api(papel).post(_url("aceitar", chamado)).status_code == 403


def test_prestador_nao_cancela(cliente_api, prestador) -> None:
    chamado = _no_status(Status.ACEITO, prestador)

    response = cliente_api(usuario=prestador.usuario).post(
        _url("cancelar", chamado), {"motivo": "x"}, format="json"
    )

    assert response.status_code == 403
