from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from apps.chamados.models import Chamado, Status
from apps.contas.models import Papel
from apps.financeiro import services, tasks
from apps.financeiro.models import Fechamento, FechamentoItem, TipoFechamento
from config.settings import CELERY_BEAT_SCHEDULE
from core.exceptions import ErroDominio
from tests.concorrencia import em_paralelo
from tests.factories import ChamadoFactory, ClienteFactory, PrestadorFactory

SP = ZoneInfo("America/Sao_Paulo")
SETEMBRO = services.Periodo.mes(2026, 9)


def _local(ano: int, mes: int, dia: int, hora: int = 0, minuto: int = 0) -> datetime:
    return datetime(ano, mes, dia, hora, minuto, tzinfo=SP)


def _encerrado(
    cliente, prestador, valor: str, quando: datetime, status=Status.CONCLUIDO
) -> Chamado:
    return ChamadoFactory.create(
        cliente=cliente,
        prestador=prestador,
        status=status,
        valor_final=Decimal(valor),
        encerrado_em=quando,
    )


@pytest.fixture
def cenario() -> dict[str, Any]:
    """Setembro/2026: 2 clientes, 2 prestadores, com casos de borda."""
    c1, c2 = ClienteFactory.create(), ClienteFactory.create()
    p1, p2 = PrestadorFactory.create(), PrestadorFactory.create()
    return {
        "c1": c1,
        "c2": c2,
        "p1": p1,
        "p2": p2,
        "entram": [
            _encerrado(c1, p1, "388.40", _local(2026, 9, 1, 0, 0)),  # 1º instante do mês
            _encerrado(c1, p2, "250.00", _local(2026, 9, 15, 10, 0)),
            _encerrado(c2, p1, "331.00", _local(2026, 9, 30, 23, 59)),  # = 01/10 02:59 UTC
            _encerrado(c2, p1, "250.00", _local(2026, 9, 20, 8, 0), Status.CANCELADO),  # c/ taxa
        ],
        "ficam_fora": [
            _encerrado(c1, p1, "0.00", _local(2026, 9, 10, 9, 0), Status.CANCELADO),  # sem taxa
            _encerrado(c1, p1, "999.00", _local(2026, 10, 1, 0, 0)),  # já é outubro
            _encerrado(c2, p2, "999.00", _local(2026, 8, 31, 23, 59)),  # ainda agosto
            ChamadoFactory.create(cliente=c1, prestador=p1, status=Status.EM_ATENDIMENTO),
        ],
    }


def _por_destino(tipo: TipoFechamento) -> dict[int, tuple[Decimal, int]]:
    campo = "cliente_id" if tipo == TipoFechamento.CLIENTE else "prestador_id"
    return {
        f[campo]: (f["total"], f["quantidade_chamados"])
        for f in Fechamento.objects.filter(tipo=tipo).values(campo, "total", "quantidade_chamados")
    }


# --- geração -------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_fecha_por_cliente_e_por_prestador(cenario) -> None:
    resultado = services.gerar(SETEMBRO)

    c1, c2, p1, p2 = cenario["c1"], cenario["c2"], cenario["p1"], cenario["p2"]
    assert _por_destino(TipoFechamento.CLIENTE) == {
        c1.pk: (Decimal("638.40"), 2),
        c2.pk: (Decimal("581.00"), 2),
    }
    assert _por_destino(TipoFechamento.PRESTADOR) == {
        p1.pk: (Decimal("969.40"), 3),
        p2.pk: (Decimal("250.00"), 1),
    }
    assert resultado[TipoFechamento.CLIENTE] == services.Resultado(fechamentos=2, itens=4)
    assert resultado[TipoFechamento.PRESTADOR] == services.Resultado(fechamentos=2, itens=4)
    incluidos = set(FechamentoItem.objects.values_list("chamado_id", flat=True))
    assert incluidos == {c.pk for c in cenario["entram"]}
    f = Fechamento.objects.filter(tipo=TipoFechamento.CLIENTE).first()
    assert f is not None
    assert (f.periodo_inicio, f.periodo_fim) == (date(2026, 9, 1), date(2026, 9, 30))


@pytest.mark.django_db
def test_total_e_sempre_a_soma_dos_itens(cenario) -> None:
    services.gerar(SETEMBRO)

    for f in Fechamento.objects.prefetch_related("itens"):
        assert f.total == sum(i.valor for i in f.itens.all())
        assert f.quantidade_chamados == len(f.itens.all())


@pytest.mark.django_db
def test_repasse_percentual_arredonda_por_chamado(cenario, settings) -> None:
    settings.REPASSE_PRESTADOR_PERCENTUAL = 75

    services.gerar(SETEMBRO)

    # p1: 388,40×0,75=291,30 + 331,00×0,75=248,25 + 250,00×0,75=187,50
    assert _por_destino(TipoFechamento.PRESTADOR)[cenario["p1"].pk] == (Decimal("727.05"), 3)
    # Cliente continua pagando o valor cheio.
    assert _por_destino(TipoFechamento.CLIENTE)[cenario["c1"].pk] == (Decimal("638.40"), 2)


@pytest.mark.django_db
def test_rodar_de_novo_nao_duplica(cenario) -> None:
    services.gerar(SETEMBRO)

    segunda = services.gerar(SETEMBRO)

    assert segunda[TipoFechamento.CLIENTE] == services.Resultado(0, 0)
    assert segunda[TipoFechamento.PRESTADOR] == services.Resultado(0, 0)
    assert Fechamento.objects.count() == 4
    assert FechamentoItem.objects.count() == 8


@pytest.mark.django_db
def test_duas_queries_independente_do_volume(cenario, django_assert_num_queries) -> None:
    for _ in range(20):
        _encerrado(cenario["c1"], cenario["p1"], "100.00", _local(2026, 9, 5, 12, 0))

    # SAVEPOINT, 1 comando por tipo (INSERT fechamentos + INSERT itens numa CTE), RELEASE
    with django_assert_num_queries(4):
        services.gerar(SETEMBRO)


@pytest.mark.django_db
def test_periodo_em_andamento_e_recusado() -> None:
    hoje = timezone.localdate()

    with pytest.raises(ErroDominio) as erro:
        services.gerar(services.Periodo.mes(hoje.year, hoje.month))

    assert erro.value.codigo == "periodo_em_andamento"


@pytest.mark.django_db
def test_filtro_do_mes_usa_o_indice_parcial_de_encerramento() -> None:
    desde, ate = SETEMBRO.limites()
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(
            "EXPLAIN SELECT 1 FROM chamados_chamado c WHERE " + services._FILTRO,
            {"desde": desde, "ate": ate},
        )
        plano = "\n".join(linha[0] for linha in cursor.fetchall())

    assert "chamado_encerrado" in plano


@pytest.mark.django_db(transaction=True)
def test_geracoes_simultaneas_nao_duplicam(cenario) -> None:
    em_paralelo(4, lambda _: services.gerar(SETEMBRO))

    assert Fechamento.objects.count() == 4
    assert FechamentoItem.objects.count() == 8


def test_mes_anterior_inclusive_na_virada_do_ano() -> None:
    assert services.Periodo.mes_anterior(date(2027, 1, 1)) == services.Periodo.mes(2026, 12)
    assert services.Periodo.mes_anterior(date(2026, 3, 1)) == services.Periodo(
        date(2026, 2, 1), date(2026, 2, 28)
    )


def test_beat_gera_no_dia_1_as_3h() -> None:
    agendamento = CELERY_BEAT_SCHEDULE["gerar-fechamentos"]

    assert agendamento["task"] == "apps.financeiro.tasks.gerar_fechamentos_mes_anterior"
    cron = agendamento["schedule"]
    assert (cron.day_of_month, cron.hour, cron.minute) == ({1}, {3}, {0})


# --- API -----------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_gerar_pela_api_dispara_tarefa(cliente_api, monkeypatch) -> None:
    chamadas = []

    class Resultado:
        id = "tarefa-123"

    def delay(*args: int) -> Resultado:
        chamadas.append(args)
        return Resultado()

    monkeypatch.setattr(tasks.gerar_fechamentos, "delay", delay)

    response = cliente_api(Papel.FINANCEIRO).post(
        reverse("fechamentos-gerar"), {"ano": 2026, "mes": 9}, format="json"
    )

    assert response.status_code == 202
    assert response.json() == {"tarefa": "tarefa-123", "periodo": "2026-09"}
    assert chamadas == [(2026, 9)]


@pytest.mark.django_db
def test_gerar_mes_corrente_pela_api_responde_422_sem_enfileirar(cliente_api, monkeypatch) -> None:
    monkeypatch.setattr(tasks.gerar_fechamentos, "delay", lambda *a: pytest.fail("enfileirou"))
    hoje = timezone.localdate()

    response = cliente_api(Papel.FINANCEIRO).post(
        reverse("fechamentos-gerar"), {"ano": hoje.year, "mes": hoje.month}, format="json"
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_task_gera_e_resume(cenario) -> None:
    assert tasks.gerar_fechamentos.apply(args=(2026, 9)).get() == {"CLIENTE": 2, "PRESTADOR": 2}


@pytest.mark.django_db
def test_lista_filtrada_em_uma_query(cenario, cliente_api, django_assert_num_queries) -> None:
    services.gerar(SETEMBRO)
    client = cliente_api(Papel.FINANCEIRO)

    with django_assert_num_queries(1):
        response = client.get(reverse("fechamentos"), {"tipo": "CLIENTE", "periodo": "2026-09"})

    resultados = response.json()["results"]
    assert {f["cliente"]["id"] for f in resultados} == {cenario["c1"].pk, cenario["c2"].pk}
    assert all(f["prestador"] is None for f in resultados)
    assert client.get(reverse("fechamentos"), {"periodo": "2026-08"}).json()["results"] == []
    assert client.get(reverse("fechamentos"), {"periodo": "09-2026"}).status_code == 400


@pytest.mark.django_db
def test_detalhe_com_itens_em_duas_queries(cenario, cliente_api, django_assert_num_queries) -> None:
    services.gerar(SETEMBRO)
    fechamento = Fechamento.objects.get(tipo=TipoFechamento.CLIENTE, cliente=cenario["c1"])
    client = cliente_api(Papel.FINANCEIRO)

    with django_assert_num_queries(2):
        response = client.get(reverse("fechamento-detalhe", args=[fechamento.pk]))

    body = response.json()
    assert body["total"] == "638.40"
    assert [i["valor"] for i in body["itens"]] == ["388.40", "250.00"]  # por encerramento
    assert body["itens"][0]["placa"] == "ABC1D23"


@pytest.mark.django_db
@pytest.mark.parametrize("papel", [Papel.ATENDENTE, Papel.DESPACHANTE, Papel.PRESTADOR])
def test_so_financeiro_acessa_fechamentos(cliente_api, papel) -> None:
    client = cliente_api(papel)

    assert client.get(reverse("fechamentos")).status_code == 403
    assert client.post(reverse("fechamentos-gerar"), {"ano": 2026, "mes": 9}).status_code == 403
