import json
import threading
import time
from collections.abc import Iterator
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.urls import reverse

from apps.chamados import distancia
from apps.chamados.distancia import CHAVE_PAUSA, LinhaRetaPostGIS, RotaOSRM
from apps.chamados.models import Chamado, FonteDistancia
from apps.contas.models import Papel
from tests.factories import ClienteFactory

pytestmark = pytest.mark.django_db

SE = Point(-46.6339, -23.5503, srid=4326)
GRU = Point(-46.4731, -23.4356, srid=4326)
PAULISTA = Point(-46.6544, -23.5614, srid=4326)
ROTA_OK = {"code": "Ok", "routes": [{"distance": 28_734.6, "duration": 1900.2}]}


class OSRMFalso:
    """Servidor HTTP real numa thread: o `httpx` faz o caminho de rede completo."""

    def __init__(self) -> None:
        self.resposta: tuple[int, Any] = (200, ROTA_OK)
        self.atraso = 0.0
        self.pedidos: list[str] = []
        falso = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                falso.pedidos.append(self.path)
                time.sleep(falso.atraso)
                status, corpo = falso.resposta
                dados = corpo.encode() if isinstance(corpo, str) else json.dumps(corpo).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

            def log_message(self, *args: Any) -> None:
                pass

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.servidor.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.servidor.server_port}"
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def fechar(self) -> None:
        self.servidor.shutdown()
        self.servidor.server_close()


@pytest.fixture
def osrm(settings) -> Iterator[OSRMFalso]:
    falso = OSRMFalso()
    settings.DISTANCIA_PROVEDOR = "osrm"
    settings.OSRM_URL = falso.url
    settings.OSRM_TIMEOUT_SEGUNDOS = 0.2
    yield falso
    falso.fechar()


def _rota(osrm: OSRMFalso) -> RotaOSRM:
    return RotaOSRM(osrm.url, timeout=0.2, fator_estimativa=Decimal("1.3"))


def _estimada(origem: Point, destino: Point) -> Decimal:
    reta = LinhaRetaPostGIS().medir(origem, destino).km
    return (reta * Decimal("1.3")).quantize(Decimal("0.01"))


# --- caminho feliz -------------------------------------------------------------------------------


def test_usa_a_distancia_da_rota(osrm) -> None:
    medida = _rota(osrm).medir(SE, GRU)

    assert (medida.km, medida.fonte) == (Decimal("28.73"), FonteDistancia.ROTA)
    caminho, _, query = osrm.pedidos[0].partition("?")
    # OSRM espera lng,lat; e não pedimos geometria nem passos.
    assert caminho == "/route/v1/driving/-46.633900,-23.550300;-46.473100,-23.435600"
    assert parse_qs(query) == {
        "overview": ["false"],
        "alternatives": ["false"],
        "steps": ["false"],
    }


def test_rota_fica_em_cache_inclusive_para_pontos_a_poucos_metros(osrm) -> None:
    rota = _rota(osrm)
    rota.medir(SE, GRU)

    vizinho = Point(SE.x + 0.0001, SE.y - 0.0001, srid=4326)  # ~15 m
    medida = rota.medir(vizinho, GRU)

    assert medida == distancia.Distancia(Decimal("28.73"), FonteDistancia.ROTA)
    assert len(osrm.pedidos) == 1


# --- falhas: nunca impedem o chamado -------------------------------------------------------------


def test_timeout_estima_e_pausa_as_consultas(osrm) -> None:
    osrm.atraso = 0.5
    rota = _rota(osrm)

    inicio = time.monotonic()
    medida = rota.medir(SE, GRU)
    assert time.monotonic() - inicio < 0.45  # não esperou o OSRM responder

    assert medida == distancia.Distancia(_estimada(SE, GRU), FonteDistancia.ESTIMADA)
    assert cache.get(CHAVE_PAUSA)
    # Durante a pausa, nem tenta: sem pagar outro timeout.
    osrm.atraso = 0
    assert rota.medir(PAULISTA, GRU).fonte == FonteDistancia.ESTIMADA
    assert len(osrm.pedidos) == 1


def test_estimativa_nao_vai_para_o_cache(osrm) -> None:
    osrm.resposta = (503, "indisponível")
    rota = _rota(osrm)
    assert rota.medir(SE, GRU).fonte == FonteDistancia.ESTIMADA

    cache.delete(CHAVE_PAUSA)  # pausa acabou e o OSRM voltou
    osrm.resposta = (200, ROTA_OK)

    assert rota.medir(SE, GRU).fonte == FonteDistancia.ROTA


def test_conexao_recusada_estima(osrm) -> None:
    osrm.fechar()

    medida = _rota(osrm).medir(SE, GRU)

    assert medida.fonte == FonteDistancia.ESTIMADA
    assert cache.get(CHAVE_PAUSA)


@pytest.mark.parametrize(
    "resposta", [(500, {"code": "InternalError"}), (200, "<html>proxy</html>")]
)
def test_erro_do_servico_estima_e_pausa(osrm, resposta) -> None:
    osrm.resposta = resposta

    assert _rota(osrm).medir(SE, GRU).fonte == FonteDistancia.ESTIMADA
    assert cache.get(CHAVE_PAUSA)


@pytest.mark.parametrize(
    "resposta",
    [
        (400, {"code": "NoRoute", "message": "Impossible route"}),
        (200, {"code": "Ok", "routes": []}),
    ],
)
def test_sem_rota_estima_sem_pausar_o_servico(osrm, resposta) -> None:
    osrm.resposta = resposta
    rota = _rota(osrm)

    assert rota.medir(SE, GRU).fonte == FonteDistancia.ESTIMADA
    assert cache.get(CHAVE_PAUSA) is None  # o serviço está bem; o problema era o ponto
    rota.medir(PAULISTA, GRU)
    assert len(osrm.pedidos) == 2


# --- configuração --------------------------------------------------------------------------------


def test_provedor_vem_do_settings(settings) -> None:
    assert isinstance(distancia.obter_calculadora(), LinhaRetaPostGIS)

    settings.DISTANCIA_PROVEDOR = "osrm"
    settings.OSRM_URL = "http://osrm:5000/"
    calculadora = distancia.obter_calculadora()
    assert isinstance(calculadora, RotaOSRM)
    assert calculadora.url == "http://osrm:5000"

    settings.DISTANCIA_PROVEDOR = "google"
    with pytest.raises(ImproperlyConfigured):
        distancia.obter_calculadora()


# --- pela API ------------------------------------------------------------------------------------


def _payload(cliente_id: int) -> dict[str, object]:
    return {
        "cliente_id": cliente_id,
        "placa": "ABC1D23",
        "endereco_origem": "Praça da Sé",
        "origem": {"lat": SE.y, "lng": SE.x},
        "destino": {"lat": GRU.y, "lng": GRU.x},
    }


def test_post_com_osrm_usa_km_por_estrada(cliente_api, osrm) -> None:
    response = cliente_api(Papel.ATENDENTE).post(
        reverse("chamados"), _payload(ClienteFactory().pk), format="json"
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert (body["distancia_km"], body["distancia_fonte"]) == ("28.73", "ROTA")
    assert body["valor_previsto"] == "250.00"  # 28,73 km: dentro da franquia de 40 km


def test_post_com_osrm_fora_do_ar_ainda_cria_o_chamado(cliente_api, osrm) -> None:
    osrm.fechar()

    response = cliente_api(Papel.ATENDENTE).post(
        reverse("chamados"), _payload(ClienteFactory().pk), format="json"
    )

    assert response.status_code == 201
    assert response.json()["distancia_fonte"] == "ESTIMADA"


def test_consulta_ao_osrm_acontece_fora_da_transacao(cliente_api, osrm, monkeypatch) -> None:
    """Com Idempotency-Key, o chamado nasce dentro de um atomic(): o HTTP tem que vir antes."""
    # O próprio teste já roda numa transação: vale a profundidade relativa a ela.
    profundidade_do_teste = len(connection.atomic_blocks)
    profundidades: list[int] = []
    original = RotaOSRM._consultar

    def espiar(self: RotaOSRM, origem: Point, destino: Point) -> float:
        profundidades.append(len(connection.atomic_blocks))
        return original(self, origem, destino)

    monkeypatch.setattr(RotaOSRM, "_consultar", espiar)

    response = cliente_api(Papel.ATENDENTE).post(
        reverse("chamados"),
        _payload(ClienteFactory().pk),
        format="json",
        HTTP_IDEMPOTENCY_KEY="rota-1",
    )

    assert response.status_code == 201
    assert profundidades == [profundidade_do_teste]
    assert Chamado.objects.get().distancia_fonte == FonteDistancia.ROTA


def test_reenvio_com_a_mesma_chave_nao_consulta_o_osrm(cliente_api, osrm) -> None:
    client = cliente_api(Papel.ATENDENTE)
    payload = _payload(ClienteFactory().pk)
    client.post(reverse("chamados"), payload, format="json", HTTP_IDEMPOTENCY_KEY="rota-2")
    cache.clear()  # sem a rota em cache: só a idempotência pode evitar a nova consulta

    response = client.post(
        reverse("chamados"), payload, format="json", HTTP_IDEMPOTENCY_KEY="rota-2"
    )

    assert response["Idempotent-Replayed"] == "true"
    assert len(osrm.pedidos) == 1
