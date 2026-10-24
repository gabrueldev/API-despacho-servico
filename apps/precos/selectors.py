from django.core.cache import cache

from core.exceptions import NaoEncontrado

from .calculo import Tabela
from .models import TabelaPrecos

TTL_SEGUNDOS = 60 * 60


def _chave(tabela_id: int) -> str:
    return f"precos:tabela:{tabela_id}"


def obter_tabela(tabela_id: int) -> Tabela:
    """Tabela de preços via cache (Redis). Guarda um dataclass pequeno, não o model."""
    tabela: Tabela | None = cache.get(_chave(tabela_id))
    if tabela is None:
        try:
            tabela = TabelaPrecos.objects.get(pk=tabela_id).dados()
        except TabelaPrecos.DoesNotExist as exc:
            raise NaoEncontrado("Tabela de preços não encontrada.") from exc
        cache.set(_chave(tabela_id), tabela, timeout=TTL_SEGUNDOS)
    return tabela


def invalidar_tabela(tabela_id: int) -> None:
    cache.delete(_chave(tabela_id))
