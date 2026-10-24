"""Máquina de estados do chamado — regras puras, sem banco.

ABERTO ─► DESPACHADO ─► ACEITO ─► A_CAMINHO ─► NO_LOCAL ─► EM_ATENDIMENTO ─► CONCLUIDO
              │
              └─(recusa ou timeout de aceite)─► ABERTO
Qualquer status não encerrado ─► CANCELADO (com taxa a partir de A_CAMINHO).
"""

from .models import Status

TRANSICOES: dict[Status, frozenset[Status]] = {
    Status.ABERTO: frozenset({Status.DESPACHADO, Status.CANCELADO}),
    Status.DESPACHADO: frozenset({Status.ACEITO, Status.ABERTO, Status.CANCELADO}),
    Status.ACEITO: frozenset({Status.A_CAMINHO, Status.CANCELADO}),
    Status.A_CAMINHO: frozenset({Status.NO_LOCAL, Status.CANCELADO}),
    Status.NO_LOCAL: frozenset({Status.EM_ATENDIMENTO, Status.CANCELADO}),
    Status.EM_ATENDIMENTO: frozenset({Status.CONCLUIDO, Status.CANCELADO}),
    Status.CONCLUIDO: frozenset(),
    Status.CANCELADO: frozenset(),
}

# Avanços que o próprio prestador informa em POST /chamados/{id}/status.
AVANCOS_DO_PRESTADOR = (Status.A_CAMINHO, Status.NO_LOCAL, Status.EM_ATENDIMENTO)

# A partir daqui o prestador já se deslocou: cancelar cobra a taxa de saída.
COBRA_TAXA_CANCELAMENTO = frozenset({Status.A_CAMINHO, Status.NO_LOCAL, Status.EM_ATENDIMENTO})


def pode_transicionar(de: Status, para: Status) -> bool:
    return para in TRANSICOES[de]


def cobra_taxa_cancelamento(de: Status) -> bool:
    return de in COBRA_TAXA_CANCELAMENTO
