"""Cálculo de valores — funções puras, sem banco (testáveis sem Django configurado).

Regras (plano §10.1):
- `valor_saida` inclui a franquia de km; acima dela, cada km **inteiro iniciado** é cobrado.
- Espera cobrada por hora, em frações de 15 min arredondadas para cima.
- Cada item é arredondado para 2 casas com ROUND_HALF_UP; o total é a soma dos itens.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from .tipos import TipoItem

CENTAVOS = Decimal("0.01")
MINUTOS_POR_FRACAO = 15
HORAS_POR_FRACAO = Decimal("0.25")


@dataclass(frozen=True, slots=True)
class Tabela:
    valor_saida: Decimal
    valor_km_excedente: Decimal
    km_franquia: Decimal
    valor_hora_espera: Decimal


@dataclass(frozen=True, slots=True)
class ItemCalculado:
    tipo: TipoItem
    descricao: str
    quantidade: Decimal
    valor_unitario: Decimal

    @property
    def total(self) -> Decimal:
        return arredondar(self.quantidade * self.valor_unitario)


def arredondar(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def itens_deslocamento(tabela: Tabela, distancia_km: Decimal) -> list[ItemCalculado]:
    itens = [ItemCalculado(TipoItem.SAIDA, "Saída", Decimal(1), tabela.valor_saida)]
    excedente = (distancia_km - tabela.km_franquia).to_integral_value(rounding=ROUND_CEILING)
    if excedente > 0:
        itens.append(
            ItemCalculado(
                TipoItem.KM_EXCEDENTE,
                f"{excedente} km acima da franquia de {tabela.km_franquia} km",
                excedente,
                tabela.valor_km_excedente,
            )
        )
    return itens


def item_espera(tabela: Tabela, minutos: int) -> ItemCalculado | None:
    if minutos <= 0:
        return None
    fracoes = -(-minutos // MINUTOS_POR_FRACAO)  # divisão com teto
    return ItemCalculado(
        TipoItem.ESPERA,
        f"{minutos} min de espera",
        fracoes * HORAS_POR_FRACAO,
        tabela.valor_hora_espera,
    )


def total(itens: Iterable[ItemCalculado]) -> Decimal:
    return sum((item.total for item in itens), Decimal("0.00"))
