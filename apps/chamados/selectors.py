from django.db.models import Prefetch, QuerySet, Subquery
from django.utils import timezone

from apps.contas.models import Papel, Usuario
from apps.prestadores import localizacao
from apps.prestadores.models import Prestador
from core.exceptions import ErroDominio, NaoEncontrado

from .models import Chamado, EventoChamado, Status

CAMPOS_LISTA = (
    "id",
    "status",
    "placa",
    "valor_previsto",
    "valor_final",
    "criado_em",
    "cliente__id",
    "cliente__nome",
    "prestador__id",
    "prestador__nome",
)


def chamados_visiveis(usuario: Usuario) -> QuerySet[Chamado]:
    """Prestador só enxerga os próprios chamados; atendente e despachante, todos.

    Subquery escalar em vez de JOIN: o Postgres a resolve antes (InitPlan) e usa
    `prestador_id = $0` como condição do índice `chamado_prestador_criado`, que já entrega
    em ordem de `criado_em` e para no LIMIT. Com o JOIN, ele lia todo o histórico do
    prestador e ordenava em memória.
    """
    qs = Chamado.objects.all()
    if usuario.papel == Papel.PRESTADOR:
        meu_id = Prestador.objects.filter(usuario_id=usuario.pk).values("id")[:1]
        qs = qs.filter(prestador_id=Subquery(meu_id))
    return qs


def listar_chamados(usuario: Usuario, status: Status | None = None) -> QuerySet[Chamado]:
    """Uma query só: JOIN em cliente/prestador e só as colunas da listagem."""
    qs = chamados_visiveis(usuario).select_related("cliente", "prestador").only(*CAMPOS_LISTA)
    if status:
        qs = qs.filter(status=status)
    return qs


def detalhe_chamados(usuario: Usuario) -> QuerySet[Chamado]:
    """3 queries fixas: chamado (+ cliente/prestador), itens e eventos."""
    return (
        chamados_visiveis(usuario)
        .select_related("cliente", "prestador")
        .prefetch_related(
            "itens",
            Prefetch("eventos", queryset=EventoChamado.objects.order_by("criado_em", "id")),
        )
    )


# Só nestes status a posição do prestador interessa ao associado.
STATUS_COM_POSICAO = (Status.ACEITO, Status.A_CAMINHO, Status.NO_LOCAL, Status.EM_ATENDIMENTO)


class RastreioExpirado(ErroDominio):
    codigo = "rastreio_expirado"
    status_http = 410


def mascarar_placa(placa: str) -> str:
    return f"{placa[:3]}-**{placa[-2:]}"


def rastreio(token: str) -> dict[str, object]:
    """Visão pública do chamado: 1 query (índice único do token) + 1 leitura no Redis."""
    chamado = (
        Chamado.objects.select_related("prestador")
        .only(
            "status",
            "placa",
            "origem",
            "rastreio_expira_em",
            "prestador__nome",
            "prestador__usuario_id",
        )
        .filter(rastreio_token=token)
        .first()
    )
    if chamado is None:
        raise NaoEncontrado("Rastreio não encontrado.")
    if chamado.rastreio_expira_em and chamado.rastreio_expira_em <= timezone.now():
        raise RastreioExpirado("Este link de rastreio expirou.")

    prestador = chamado.prestador
    posicao = None
    if prestador and chamado.status in STATUS_COM_POSICAO:
        posicao = localizacao.ultima_posicao(prestador.usuario_id)
    return {
        "status": chamado.status,
        "placa": mascarar_placa(chamado.placa),
        "origem": {"lat": chamado.origem.y, "lng": chamado.origem.x},
        "prestador": {"nome": prestador.nome, "posicao": posicao} if prestador else None,
        "expira_em": chamado.rastreio_expira_em,
    }
