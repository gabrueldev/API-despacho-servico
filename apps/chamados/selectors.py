from django.db.models import Prefetch, QuerySet

from apps.contas.models import Papel, Usuario

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
    """Prestador só enxerga os próprios chamados; atendente e despachante, todos."""
    qs = Chamado.objects.all()
    if usuario.papel == Papel.PRESTADOR:
        qs = qs.filter(prestador__usuario_id=usuario.pk)
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
