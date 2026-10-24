from rest_framework.pagination import CursorPagination


class CriadoEmCursorPagination(CursorPagination):
    """Cursor estável: `id` desempata registros com o mesmo `criado_em`.

    A ordenação precisa bater com os índices compostos `(..., criado_em, id)`.
    """

    ordering = ("-criado_em", "-id")
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
