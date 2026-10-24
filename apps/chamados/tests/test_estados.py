import pytest

from apps.chamados import estados
from apps.chamados.models import Status

S = Status
FLUXO_FELIZ = [
    (S.ABERTO, S.DESPACHADO),
    (S.DESPACHADO, S.ACEITO),
    (S.ACEITO, S.A_CAMINHO),
    (S.A_CAMINHO, S.NO_LOCAL),
    (S.NO_LOCAL, S.EM_ATENDIMENTO),
    (S.EM_ATENDIMENTO, S.CONCLUIDO),
]
VALIDAS = {
    *FLUXO_FELIZ,
    (S.DESPACHADO, S.ABERTO),  # recusa / timeout
    *((de, S.CANCELADO) for de in S if de not in (S.CONCLUIDO, S.CANCELADO)),
}


@pytest.mark.parametrize(("de", "para"), [(de, para) for de in S for para in S])
def test_matriz_completa_de_transicoes(de: Status, para: Status) -> None:
    assert estados.pode_transicionar(de, para) is ((de, para) in VALIDAS)


@pytest.mark.parametrize("encerrado", [S.CONCLUIDO, S.CANCELADO])
def test_encerrados_sao_finais(encerrado: Status) -> None:
    assert not any(estados.pode_transicionar(encerrado, para) for para in S)


@pytest.mark.parametrize(
    ("de", "cobra"),
    [
        (S.ABERTO, False),
        (S.DESPACHADO, False),
        (S.ACEITO, False),
        (S.A_CAMINHO, True),
        (S.NO_LOCAL, True),
        (S.EM_ATENDIMENTO, True),
    ],
)
def test_taxa_de_cancelamento_a_partir_de_a_caminho(de: Status, cobra: bool) -> None:
    assert estados.cobra_taxa_cancelamento(de) is cobra
