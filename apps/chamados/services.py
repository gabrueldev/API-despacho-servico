from dataclasses import dataclass

from django.contrib.gis.geos import Point
from django.db import transaction

from apps.clientes.models import Cliente
from apps.contas.models import Usuario
from apps.precos import calculo
from apps.precos.selectors import obter_tabela
from core.exceptions import ErroDominio

from .distancia import CalculadoraDistancia, calculadora_padrao
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
    calculadora: CalculadoraDistancia = calculadora_padrao,
) -> ChamadoCriado:
    cliente = (
        Cliente.objects.filter(pk=dados.cliente_id, ativo=True)
        .only("id", "tabela_precos_id")
        .first()
    )
    if cliente is None:
        raise ErroDominio("Cliente inexistente ou inativo.", codigo="cliente_invalido")

    # Leituras fora da transação: ela fica curta e só com escritas.
    tabela = obter_tabela(cliente.tabela_precos_id)
    distancia_km = calculadora.distancia_km(dados.origem, dados.destino)
    previstos = calculo.itens_deslocamento(tabela, distancia_km)
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
            distancia_km=distancia_km,
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
            dados={"valor_previsto": str(valor_previsto), "distancia_km": str(distancia_km)},
        )

    return ChamadoCriado(chamado=chamado, itens=itens)
