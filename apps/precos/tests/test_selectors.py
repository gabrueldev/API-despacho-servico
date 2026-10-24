from decimal import Decimal

import pytest

from apps.precos.selectors import obter_tabela
from core.exceptions import NaoEncontrado
from tests.factories import TabelaPrecosFactory

pytestmark = pytest.mark.django_db


def test_segunda_leitura_vem_do_cache(django_assert_num_queries) -> None:
    tabela = TabelaPrecosFactory()

    with django_assert_num_queries(1):
        obter_tabela(tabela.pk)
    with django_assert_num_queries(0):
        assert obter_tabela(tabela.pk).valor_saida == Decimal("250.00")


def test_editar_tabela_invalida_o_cache(django_capture_on_commit_callbacks) -> None:
    tabela = TabelaPrecosFactory()
    obter_tabela(tabela.pk)

    with django_capture_on_commit_callbacks(execute=True):
        tabela.valor_saida = Decimal("300.00")
        tabela.save()

    assert obter_tabela(tabela.pk).valor_saida == Decimal("300.00")


def test_tabela_inexistente() -> None:
    with pytest.raises(NaoEncontrado):
        obter_tabela(999_999)
