import math
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone

from apps.contas.models import Papel
from apps.prestadores import localizacao
from apps.prestadores.management.commands.simular_frota import METROS_POR_GRAU, passo
from apps.prestadores.models import Prestador
from tests.factories import PrestadorFactory

pytestmark = pytest.mark.django_db

URL_ME = reverse("prestador-me")


# --- GET /prestadores/me -------------------------------------------------------------------------


def test_perfil_usa_a_posicao_mais_recente_do_redis(cliente_api, django_assert_num_queries) -> None:
    prestador = PrestadorFactory.create(nome="Guincho 7")
    localizacao.registrar(prestador.usuario_id, -23.5612, -46.656)
    client = cliente_api(usuario=prestador.usuario)

    with django_assert_num_queries(1):
        response = client.get(URL_ME)

    body = response.json()
    assert (body["id"], body["nome"], body["disponivel"]) == (prestador.pk, "Guincho 7", True)
    assert (body["posicao"]["lat"], body["posicao"]["lng"]) == (-23.5612, -46.656)
    assert body["posicao"]["registrado_em"]


def test_perfil_sem_posicao_no_redis_usa_a_do_banco(cliente_api) -> None:
    prestador = PrestadorFactory.create()

    body = cliente_api(usuario=prestador.usuario).get(URL_ME).json()

    assert body["posicao"] == {"lat": -23.55, "lng": -46.63, "registrado_em": None}


def test_perfil_sem_posicao_nenhuma(cliente_api) -> None:
    prestador = PrestadorFactory.create(localizacao=None)

    assert cliente_api(usuario=prestador.usuario).get(URL_ME).json()["posicao"] is None


def test_usuario_prestador_sem_cadastro_recebe_404(cliente_api) -> None:
    assert cliente_api(Papel.PRESTADOR).get(URL_ME).status_code == 404


def test_so_prestador_acessa_o_perfil(cliente_api) -> None:
    assert cliente_api(Papel.DESPACHANTE).get(URL_ME).status_code == 403


# --- simular_frota -------------------------------------------------------------------------------


def test_passo_desloca_a_distancia_pedida() -> None:
    lat, lng = passo(-23.55, -46.63, 1000, 90)  # 1 km para leste

    dx = (lng + 46.63) * METROS_POR_GRAU * math.cos(math.radians(-23.55))
    assert lat == pytest.approx(-23.55)
    assert dx == pytest.approx(1000, rel=1e-6)


def test_frota_move_so_os_disponiveis_e_grava_no_banco() -> None:
    livre = PrestadorFactory.create(disponivel=True)
    ocupado = PrestadorFactory.create(disponivel=False)
    antigo = timezone.now() - timedelta(hours=1)
    Prestador.objects.update(atualizado_em=antigo)
    saida = StringIO()

    call_command("simular_frota", rodadas=1, passo=200, stdout=saida)

    assert "1 prestadores movidos, 1 gravados" in saida.getvalue()
    livre.refresh_from_db()
    ocupado.refresh_from_db()
    assert livre.atualizado_em > antigo  # volta a aparecer na busca por proximidade
    assert ocupado.atualizado_em == antigo
    assert livre.localizacao is not None and ocupado.localizacao is not None
    assert livre.localizacao.distance(ocupado.localizacao) > 0
    assert localizacao.ultima_posicao(ocupado.usuario_id) is None


def test_frota_continua_de_onde_parou() -> None:
    prestador = PrestadorFactory.create()

    call_command("simular_frota", rodadas=1, stdout=StringIO())
    primeira = localizacao.ultima_posicao(prestador.usuario_id)
    call_command("simular_frota", rodadas=1, stdout=StringIO())
    segunda = localizacao.ultima_posicao(prestador.usuario_id)

    assert primeira and segunda
    metros = math.dist(
        (primeira["lat"] * METROS_POR_GRAU, primeira["lng"] * METROS_POR_GRAU * 0.92),
        (segunda["lat"] * METROS_POR_GRAU, segunda["lng"] * METROS_POR_GRAU * 0.92),
    )
    assert metros <= 151  # um passo a partir da 1ª posição, não do ponto original


def test_frota_recusa_parametros_invalidos() -> None:
    with pytest.raises(CommandError):
        call_command("simular_frota", rodadas=1, passo=0)
