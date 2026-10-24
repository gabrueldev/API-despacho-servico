import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.contas.models import Papel
from apps.contas.urls import LoginSerializer
from apps.prestadores import localizacao, tasks
from apps.prestadores.models import Prestador
from tests.factories import PrestadorFactory, UsuarioFactory

URL = reverse("prestador-localizacao")
SE = {"lat": -23.5503, "lng": -46.6339}


def _client_com_jwt(usuario) -> APIClient:
    client = APIClient()
    token = LoginSerializer.get_token(usuario).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _pendentes() -> set[int]:
    return {int(i) for i in localizacao._redis().smembers(localizacao.CHAVE_PENDENTES)}


# --- endpoint ------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_envio_de_localizacao_nao_toca_o_postgres(django_assert_num_queries) -> None:
    prestador = PrestadorFactory.create()
    client = _client_com_jwt(prestador.usuario)

    with django_assert_num_queries(0):
        response = client.post(URL, {"posicao": SE}, format="json")

    assert response.status_code == 200, response.json()
    assert response.json() == {"mudou": True}
    posicao = localizacao.ultima_posicao(prestador.usuario_id)
    assert posicao is not None
    assert (posicao["lat"], posicao["lng"]) == (SE["lat"], SE["lng"])
    assert posicao["registrado_em"]


@pytest.mark.django_db
@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.DESPACHANTE])
def test_so_prestador_envia_localizacao(papel) -> None:
    response = _client_com_jwt(UsuarioFactory.create(papel=papel)).post(
        URL, {"posicao": SE}, format="json"
    )

    assert response.status_code == 403


def test_sem_token_retorna_401() -> None:
    assert APIClient().post(URL, {"posicao": SE}, format="json").status_code == 401


@pytest.mark.django_db
def test_rate_limit_por_prestador() -> None:
    client = _client_com_jwt(PrestadorFactory.create().usuario)

    codigos = [client.post(URL, {"posicao": SE}, format="json").status_code for _ in range(7)]

    assert codigos == [200] * 6 + [429]


# --- Redis ---------------------------------------------------------------------------------------


def test_so_movimento_real_entra_na_fila_de_gravacao() -> None:
    assert localizacao.registrar(10, -23.550300, -46.633900) is True
    assert localizacao.registrar(10, -23.550300, -46.633900) is False  # parado
    assert localizacao.registrar(10, -23.5503004, -46.6339003) is False  # ruído < 1 m
    assert localizacao.registrar(10, -23.551000, -46.633900) is True  # ~78 m
    assert _pendentes() == {10}


# --- gravação em lote ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_grava_todos_os_pendentes_em_um_unico_update(django_assert_num_queries) -> None:
    prestadores = [PrestadorFactory.create(localizacao=None) for _ in range(3)]
    for i, p in enumerate(prestadores):
        localizacao.registrar(p.usuario_id, -23.55 - i / 100, -46.63)

    with django_assert_num_queries(3):  # SAVEPOINT, UPDATE ... FROM (VALUES ...), RELEASE
        assert tasks.gravar_localizacoes.apply().get() == 3

    for i, p in enumerate(prestadores):
        p.refresh_from_db()
        assert p.localizacao is not None
        assert (round(p.localizacao.y, 5), p.localizacao.x) == (round(-23.55 - i / 100, 5), -46.63)
    assert _pendentes() == set()


@pytest.mark.django_db
def test_sem_pendentes_nao_vai_ao_banco(django_assert_num_queries) -> None:
    with django_assert_num_queries(0):
        assert localizacao.gravar_pendentes() == 0


@pytest.mark.django_db
def test_lote_que_falha_volta_para_a_fila(monkeypatch) -> None:
    prestador = PrestadorFactory.create()
    localizacao.registrar(prestador.usuario_id, -23.55, -46.63)

    def quebra(_lote):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(localizacao, "_gravar_lote", quebra)
    with pytest.raises(RuntimeError):
        localizacao.gravar_pendentes()

    assert _pendentes() == {prestador.usuario_id}


@pytest.mark.django_db
def test_posicao_de_usuario_sem_prestador_e_ignorada() -> None:
    usuario = UsuarioFactory.create(papel=Papel.PRESTADOR)  # sem cadastro de Prestador
    localizacao.registrar(usuario.pk, -23.55, -46.63)

    assert localizacao.gravar_pendentes() == 0
    assert not Prestador.objects.exists()
