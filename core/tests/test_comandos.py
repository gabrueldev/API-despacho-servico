from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum

from apps.chamados.distancia import LinhaRetaPostGIS
from apps.chamados.models import Chamado, Status
from apps.contas.models import Usuario
from apps.financeiro.models import Fechamento
from apps.prestadores.models import Prestador

pytestmark = pytest.mark.django_db

PEQUENO = {"chamados": 300, "prestadores": 20, "forcar": True}


def _seed(**opcoes: object) -> str:
    saida = StringIO()
    call_command("seed", stdout=saida, **{**PEQUENO, **opcoes})
    return saida.getvalue()


def _assinatura() -> list[tuple[str, str, str]]:
    return list(Chamado.objects.order_by("id").values_list("status", "placa", "valor_previsto"))


def test_seed_recusa_sem_debug() -> None:
    with pytest.raises(CommandError, match="DEBUG=false"):
        call_command("seed", chamados=1, prestadores=1)


def test_seed_cria_dados_consistentes() -> None:
    saida = _seed()

    assert "Criados: 300 chamados, 20 prestadores, 3 clientes" in saida
    assert Usuario.objects.filter(email="financeiro@despacha.dev").exists()
    assert set(Chamado.objects.values_list("status", flat=True)) == set(Status.values)
    # Concluído: valor final = soma dos itens; encerrado tem data e o resto não.
    for c in Chamado.objects.filter(status=Status.CONCLUIDO).annotate(soma=Sum("itens__total")):
        assert c.valor_final == c.soma
    assert not Chamado.objects.filter(status=Status.CONCLUIDO, encerrado_em=None).exists()
    assert not Chamado.objects.filter(status=Status.ABERTO, encerrado_em__isnull=False).exists()
    # Cada prestador ocupado está em no máximo um chamado em andamento, e indisponível.
    andamento = Chamado.objects.exclude(
        status__in=[Status.ABERTO, Status.CONCLUIDO, Status.CANCELADO]
    )
    ocupados = list(andamento.values_list("prestador_id", flat=True))
    assert len(ocupados) == len(set(ocupados))
    assert not Prestador.objects.filter(pk__in=ocupados, disponivel=True).exists()
    assert Prestador.objects.filter(disponivel=True).exists()
    assert Fechamento.objects.exists()


def test_seed_e_deterministico_e_nao_duplica() -> None:
    _seed()
    primeira = _assinatura()

    assert "já existem" in _seed()
    assert Chamado.objects.count() == 300

    _seed(limpar=True)
    assert _assinatura() == primeira


def test_explicar_exige_dados() -> None:
    with pytest.raises(CommandError, match="seed"):
        call_command("explicar")


def test_explicar_mostra_os_planos() -> None:
    _seed()
    saida = StringIO()

    call_command("explicar", stdout=saida)

    texto = saida.getvalue()
    assert texto.count("== ") == 6
    assert texto.count("Execution Time") == 6
    assert "chamado_criado" in texto
    assert Fechamento.objects.exists()  # o EXPLAIN ANALYZE do fechamento foi desfeito


def test_explicar_filtra_por_nome() -> None:
    _seed()
    saida = StringIO()

    call_command("explicar", so="rastreio", stdout=saida)

    assert saida.getvalue().count("== ") == 1


def test_seed_distancia_bate_com_as_coordenadas() -> None:
    _seed()

    for c in Chamado.objects.order_by("id")[:20]:
        postgis = LinhaRetaPostGIS().medir(c.origem, c.destino).km
        assert abs(c.distancia_km - postgis) <= postgis * Decimal("0.005") + Decimal("0.01")
