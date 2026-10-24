import threading
from collections.abc import Callable
from typing import Any

from django.db import connection


def em_paralelo(n: int, fn: Callable[[int], Any]) -> list[Any]:
    """Roda `fn(i)` em `n` threads liberadas juntas por uma barreira.

    Cada thread usa a própria conexão (transação independente). Devolve, por thread,
    o retorno ou a exceção levantada. Exige `django_db(transaction=True)`.
    """
    barreira = threading.Barrier(n)
    resultados: list[Any] = [None] * n

    def alvo(i: int) -> None:
        try:
            barreira.wait(timeout=10)
            resultados[i] = fn(i)
        except Exception as exc:
            resultados[i] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=alvo, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return resultados
