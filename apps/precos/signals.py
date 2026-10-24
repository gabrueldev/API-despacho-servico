from typing import Any

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import TabelaPrecos
from .selectors import invalidar_tabela


@receiver([post_save, post_delete], sender=TabelaPrecos)
def _invalidar_cache(sender: type[TabelaPrecos], instance: TabelaPrecos, **kwargs: Any) -> None:
    # Só após o commit: senão outro request pode recolocar no cache o valor antigo.
    tabela_id = instance.pk
    transaction.on_commit(lambda: invalidar_tabela(tabela_id))
