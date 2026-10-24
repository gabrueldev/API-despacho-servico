from decimal import Decimal

import pytest

from apps.precos import calculo
from apps.precos.tipos import TipoItem

TABELA = calculo.Tabela(
    valor_saida=Decimal("250.00"),
    valor_km_excedente=Decimal("4.50"),
    km_franquia=Decimal("40"),
    valor_hora_espera=Decimal("60.00"),
)


def test_exemplo_do_plano_totaliza_388_40() -> None:
    itens = [
        *calculo.itens_deslocamento(TABELA, Decimal("58")),
        calculo.item_espera(TABELA, 35),
        calculo.ItemCalculado(TipoItem.PEDAGIO, "Pedágio", Decimal(1), Decimal("12.40")),
    ]

    assert [i.total for i in itens if i] == [
        Decimal("250.00"),
        Decimal("81.00"),
        Decimal("45.00"),
        Decimal("12.40"),
    ]
    assert calculo.total(i for i in itens if i) == Decimal("388.40")


def test_dentro_da_franquia_cobra_so_saida() -> None:
    itens = calculo.itens_deslocamento(TABELA, Decimal("40.00"))

    assert [i.tipo for i in itens] == [TipoItem.SAIDA]
    assert calculo.total(itens) == Decimal("250.00")


@pytest.mark.parametrize(
    ("distancia", "km_cobrados"),
    [("40.01", 1), ("40.99", 1), ("41.00", 1), ("41.01", 2), ("57.30", 18)],
)
def test_km_excedente_arredonda_para_cima(distancia: str, km_cobrados: int) -> None:
    _, excedente = calculo.itens_deslocamento(TABELA, Decimal(distancia))

    assert excedente.quantidade == km_cobrados
    assert excedente.total == Decimal("4.50") * km_cobrados


@pytest.mark.parametrize(
    ("minutos", "horas"),
    [(1, "0.25"), (15, "0.25"), (16, "0.50"), (35, "0.75"), (60, "1.00"), (61, "1.25")],
)
def test_espera_em_fracoes_de_15_min(minutos: int, horas: str) -> None:
    item = calculo.item_espera(TABELA, minutos)

    assert item is not None
    assert item.quantidade == Decimal(horas)


def test_sem_espera_nao_gera_item() -> None:
    assert calculo.item_espera(TABELA, 0) is None


def test_arredondamento_half_up_por_item() -> None:
    tabela = calculo.Tabela(Decimal(0), Decimal(0), Decimal(0), Decimal("61.10"))

    item = calculo.item_espera(tabela, 15)  # 0.25 × 61.10 = 15.275

    assert item is not None
    assert item.total == Decimal("15.28")
