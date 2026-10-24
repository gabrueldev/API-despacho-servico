from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, transaction
from django.db.models import F, QuerySet, Sum
from django.utils import timezone
from psycopg.errors import LockNotAvailable

from apps.clientes.models import Cliente
from apps.contas.models import Usuario
from apps.precos import calculo
from apps.precos.selectors import obter_tabela
from apps.precos.tipos import TipoItem
from apps.prestadores.models import Prestador
from core.exceptions import Conflito, ErroDominio, NaoEncontrado

from . import distancia as distancias
from . import estados, selectors
from .distancia import Distancia
from .models import Chamado, EventoChamado, ItemValor, Status


@dataclass(frozen=True, slots=True)
class NovoChamado:
    cliente_id: int
    placa: str
    endereco_origem: str
    origem: Point
    destino: Point


@dataclass(frozen=True, slots=True)
class ChamadoCriado:
    chamado: Chamado
    itens: list[ItemValor]


def criar_chamado(
    *,
    atendente: Usuario,
    dados: NovoChamado,
    distancia: Distancia | None = None,
) -> ChamadoCriado:
    """`distancia` vem pronta quando quem chama está dentro de uma transação (idempotência):
    medir pode ser uma chamada HTTP ao OSRM, que não deve segurar transação aberta.
    """
    cliente = (
        Cliente.objects.filter(pk=dados.cliente_id, ativo=True)
        .only("id", "tabela_precos_id")
        .first()
    )
    if cliente is None:
        raise ErroDominio("Cliente inexistente ou inativo.", codigo="cliente_invalido")

    # Leituras fora da transação: ela fica curta e só com escritas.
    tabela = obter_tabela(cliente.tabela_precos_id)
    if distancia is None:
        distancia = distancias.medir(dados.origem, dados.destino)
    previstos = calculo.itens_deslocamento(tabela, distancia.km)
    valor_previsto = calculo.total(previstos)

    with transaction.atomic():
        chamado = Chamado.objects.create(
            cliente=cliente,
            atendente=atendente,
            status=Status.ABERTO,
            placa=dados.placa,
            endereco_origem=dados.endereco_origem,
            origem=dados.origem,
            destino=dados.destino,
            distancia_km=distancia.km,
            distancia_fonte=distancia.fonte,
            valor_previsto=valor_previsto,
        )
        itens = ItemValor.objects.bulk_create(
            ItemValor(
                chamado=chamado,
                tipo=item.tipo,
                descricao=item.descricao,
                quantidade=item.quantidade,
                valor_unitario=item.valor_unitario,
                total=item.total,
            )
            for item in previstos
        )
        EventoChamado.objects.create(
            chamado=chamado,
            usuario=atendente,
            de_status=None,
            para_status=Status.ABERTO,
            dados={
                "valor_previsto": str(valor_previsto),
                "distancia_km": str(distancia.km),
                "distancia_fonte": distancia.fonte,
            },
        )

    return ChamadoCriado(chamado=chamado, itens=itens)


# --- Ciclo de vida -----------------------------------------------------------------------------

# Colunas que as ações de estado leem e devolvem: nada além disso sai do banco.
CAMPOS_ESTADO = (
    "id",
    "status",
    "version",
    "prestador_id",
    "cliente_id",
    "valor_final",
    "encerrado_em",
)


def _carregar(usuario: Usuario, chamado_id: int) -> Chamado:
    chamado = (
        selectors.chamados_visiveis(usuario).only(*CAMPOS_ESTADO).filter(pk=chamado_id).first()
    )
    if chamado is None:
        raise NaoEncontrado("Chamado não encontrado.")
    return chamado


def _exigir_transicao(de: Status, para: Status) -> None:
    if not estados.pode_transicionar(de, para):
        raise ErroDominio(f"Transição {de} → {para} não permitida.", codigo="transicao_invalida")


def transicionar(
    chamado: Chamado,
    para: Status,
    *,
    usuario: Usuario | None,
    dados: dict[str, Any] | None = None,
    **campos: Any,
) -> Chamado:
    """Único ponto que muda o status de um chamado.

    Trava otimista: o UPDATE só acontece se `version` ainda for a lida. Uma query, sem
    `SELECT ... FOR UPDATE`; se outra operação passou na frente, nada é gravado e vira 409.
    """
    _exigir_transicao(Status(chamado.status), para)
    return _gravar_com_version(chamado, para, usuario=usuario, dados=dados, **campos)


def _gravar_com_version(
    chamado: Chamado,
    para: Status,
    *,
    usuario: Usuario | None,
    dados: dict[str, Any] | None,
    **campos: Any,
) -> Chamado:
    """UPDATE condicional por `version` + EventoChamado (auditoria de status e de valor)."""
    de = Status(chamado.status)
    agora = timezone.now()

    with transaction.atomic(savepoint=False):
        alterados = Chamado.objects.filter(pk=chamado.pk, version=chamado.version).update(
            status=para, version=F("version") + 1, atualizado_em=agora, **campos
        )
        if alterados:
            EventoChamado.objects.create(
                chamado_id=chamado.pk,
                usuario=usuario,
                de_status=de,
                para_status=para,
                dados=dados or {},
            )
    # Fora do atomic: 0 linhas = nada gravado, e a transação de quem chamou continua usável
    # (ex.: o timeout de aceite trata o 409 como "já resolvido" e segue).
    if not alterados:
        raise Conflito("O chamado foi alterado por outra operação. Recarregue e tente de novo.")

    chamado.status = para
    chamado.version += 1
    chamado.atualizado_em = agora
    for campo, valor in campos.items():
        setattr(chamado, campo, valor)
    return chamado


def _liberar_prestador(prestador_id: int | None) -> None:
    if prestador_id:
        Prestador.objects.filter(pk=prestador_id).update(disponivel=True)


def _travar_sem_esperar(qs: QuerySet[Any], pk: int, nome: str) -> Any:
    """`SELECT ... FOR UPDATE NOWAIT`: se outra transação já segura a linha, falha na hora.

    Ninguém fica parado esperando trava — nem worker do gunicorn, nem conexão do pool.
    """
    try:
        return qs.select_for_update(nowait=True).get(pk=pk)
    except DatabaseError as exc:
        if isinstance(exc.__cause__, LockNotAvailable):
            raise Conflito(f"{nome} está sendo alterado por outra operação.") from exc
        raise
    except ObjectDoesNotExist as exc:
        raise NaoEncontrado(f"{nome} não encontrado.") from exc


def despachar(*, usuario: Usuario, chamado_id: int, prestador_id: int) -> Chamado:
    """Trava pessimista: o conflito é raro, mas tem que ser 100% correto.

    Trava chamado e prestador **sempre nessa ordem** (as outras escritas seguem a mesma
    ordem), o que elimina deadlock. Quem perde recebe 409 imediatamente.
    """
    with transaction.atomic():
        chamado: Chamado = _travar_sem_esperar(
            Chamado.objects.only(*CAMPOS_ESTADO), chamado_id, "Chamado"
        )
        if chamado.status != Status.ABERTO:
            raise Conflito(f"Chamado já está {Status(chamado.status).label.lower()}.")
        prestador: Prestador = _travar_sem_esperar(
            Prestador.objects.only("id", "usuario_id", "disponivel"), prestador_id, "Prestador"
        )
        if not prestador.disponivel:
            raise Conflito("Prestador indisponível.", codigo="prestador_indisponivel")

        transicionar(
            chamado,
            Status.DESPACHADO,
            usuario=usuario,
            dados={"prestador_id": prestador.pk},
            prestador_id=prestador.pk,
        )
        Prestador.objects.filter(pk=prestador.pk).update(disponivel=False)
        transaction.on_commit(lambda: _apos_despacho(chamado, prestador))
    return chamado


def _apos_despacho(chamado: Chamado, prestador: Prestador) -> None:
    # Import local: tasks importa services.
    from core.tasks import notificar

    from .tasks import expirar_aceite

    expirar_aceite.apply_async(
        kwargs={
            "chamado_id": chamado.pk,
            "version": chamado.version,
            "prestador_id": prestador.pk,
        },
        countdown=settings.ACEITE_TIMEOUT_SEGUNDOS,
    )
    notificar.delay(
        usuario_id=prestador.usuario_id,
        tipo="chamado_despachado",
        dados={"chamado_id": chamado.pk},
        chave=f"despachado:{chamado.pk}:{chamado.version}",
    )


def expirar_aceite(*, chamado_id: int, version: int, prestador_id: int) -> bool:
    """Devolve o chamado para a fila se o prestador não aceitou a tempo.

    Zero leituras: o UPDATE condicional por `version` (a do despacho) já decide. Se o
    prestador aceitou, recusou ou o chamado foi cancelado, a version mudou → 0 linhas →
    nada acontece. Por isso a task é idempotente e pode ser reentregue sem risco.
    """
    chamado = Chamado(pk=chamado_id, status=Status.DESPACHADO, version=version)
    try:
        with transaction.atomic():
            transicionar(
                chamado,
                Status.ABERTO,
                usuario=None,
                dados={"motivo": "timeout_aceite", "prestador_id": prestador_id},
                prestador_id=None,
            )
            _liberar_prestador(prestador_id)
    except Conflito:
        return False
    return True


def aceitar(*, usuario: Usuario, chamado_id: int) -> Chamado:
    return transicionar(_carregar(usuario, chamado_id), Status.ACEITO, usuario=usuario)


def recusar(*, usuario: Usuario, chamado_id: int, motivo: str = "") -> Chamado:
    chamado = _carregar(usuario, chamado_id)
    prestador_id = chamado.prestador_id
    with transaction.atomic():
        transicionar(
            chamado,
            Status.ABERTO,
            usuario=usuario,
            dados={"prestador_id": prestador_id, "motivo": motivo},
            prestador_id=None,
        )
        _liberar_prestador(prestador_id)
    return chamado


def avancar(*, usuario: Usuario, chamado_id: int, status: Status) -> Chamado:
    if status not in estados.AVANCOS_DO_PRESTADOR:
        raise ErroDominio(
            f"Use {', '.join(estados.AVANCOS_DO_PRESTADOR)}.", codigo="status_invalido"
        )
    return transicionar(_carregar(usuario, chamado_id), status, usuario=usuario)


def concluir(*, usuario: Usuario, chamado_id: int) -> Chamado:
    chamado = _carregar(usuario, chamado_id)
    _exigir_transicao(Status(chamado.status), Status.CONCLUIDO)

    # SUM no banco. Lançar item incrementa `version` (etapa 7), então um item que chegue
    # entre esta soma e o UPDATE faz a conclusão falhar com 409 em vez de sair errada.
    soma = ItemValor.objects.filter(chamado_id=chamado.pk).aggregate(total=Sum("total"))["total"]
    valor_final = soma or Decimal("0.00")
    agora = timezone.now()

    with transaction.atomic():
        transicionar(
            chamado,
            Status.CONCLUIDO,
            usuario=usuario,
            dados={"valor_final": str(valor_final)},
            valor_final=valor_final,
            encerrado_em=agora,
            rastreio_expira_em=agora + timedelta(hours=settings.RASTREIO_VALIDADE_HORAS),
        )
        _liberar_prestador(chamado.prestador_id)
    return chamado


def cancelar(*, usuario: Usuario, chamado_id: int, motivo: str) -> Chamado:
    chamado = _carregar(usuario, chamado_id)
    de = Status(chamado.status)
    _exigir_transicao(de, Status.CANCELADO)

    taxa: calculo.ItemCalculado | None = None
    if estados.cobra_taxa_cancelamento(de):
        tabela_id = (
            Cliente.objects.filter(pk=chamado.cliente_id)
            .values_list("tabela_precos_id", flat=True)
            .get()
        )
        taxa = calculo.ItemCalculado(
            TipoItem.TAXA_CANCELAMENTO,
            f"Taxa de saída (cancelado em {de.label.lower()})",
            Decimal(1),
            obter_tabela(tabela_id).valor_saida,
        )
    valor_final = taxa.total if taxa else Decimal("0.00")
    agora = timezone.now()

    with transaction.atomic():
        transicionar(
            chamado,
            Status.CANCELADO,
            usuario=usuario,
            dados={"motivo": motivo, "taxa": str(valor_final)},
            valor_final=valor_final,
            encerrado_em=agora,
            rastreio_expira_em=agora,
        )
        if taxa:
            ItemValor.objects.create(
                chamado_id=chamado.pk,
                tipo=taxa.tipo,
                descricao=taxa.descricao,
                quantidade=taxa.quantidade,
                valor_unitario=taxa.valor_unitario,
                total=taxa.total,
            )
        _liberar_prestador(chamado.prestador_id)
    return chamado


# --- Itens de valor ----------------------------------------------------------------------------

# Pedágio pode surgir no deslocamento; nada é lançado depois de encerrado.
STATUS_ACEITAM_ITENS = (Status.A_CAMINHO, Status.NO_LOCAL, Status.EM_ATENDIMENTO)
TIPOS_LANCAVEIS = (TipoItem.PEDAGIO, TipoItem.ESPERA, TipoItem.ADICIONAL)


@dataclass(frozen=True, slots=True)
class NovoItem:
    tipo: TipoItem
    descricao: str = ""
    valor: Decimal | None = None  # PEDAGIO / ADICIONAL
    minutos: int | None = None  # ESPERA


def _calcular_item(chamado: Chamado, novo: NovoItem) -> calculo.ItemCalculado:
    if novo.tipo == TipoItem.ESPERA:
        tabela_id = (
            Cliente.objects.filter(pk=chamado.cliente_id)
            .values_list("tabela_precos_id", flat=True)
            .get()
        )
        item = calculo.item_espera(obter_tabela(tabela_id), novo.minutos or 0)
        if item is None:
            raise ErroDominio("Informe os minutos de espera.", codigo="item_invalido")
        return item
    if not novo.valor or novo.valor <= 0:
        raise ErroDominio("Informe um valor positivo.", codigo="item_invalido")
    return calculo.ItemCalculado(
        novo.tipo, novo.descricao or TipoItem(novo.tipo).label, Decimal(1), novo.valor
    )


def lancar_item(*, usuario: Usuario, chamado_id: int, novo: NovoItem) -> ItemValor:
    """Incrementa `version`: uma conclusão que somou os itens antes deste falha com 409."""
    if novo.tipo not in TIPOS_LANCAVEIS:
        raise ErroDominio(f"Use {', '.join(TIPOS_LANCAVEIS)}.", codigo="item_invalido")
    chamado = _carregar(usuario, chamado_id)
    status = Status(chamado.status)
    if status not in STATUS_ACEITAM_ITENS:
        raise ErroDominio(
            f"Itens só podem ser lançados em {', '.join(STATUS_ACEITAM_ITENS)}.",
            codigo="status_nao_aceita_itens",
        )
    calculado = _calcular_item(chamado, novo)

    with transaction.atomic():
        _gravar_com_version(
            chamado,
            status,
            usuario=usuario,
            dados={"item": calculado.tipo, "total": str(calculado.total)},
        )
        return ItemValor.objects.create(
            chamado_id=chamado.pk,
            tipo=calculado.tipo,
            descricao=calculado.descricao,
            quantidade=calculado.quantidade,
            valor_unitario=calculado.valor_unitario,
            total=calculado.total,
        )
