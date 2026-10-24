from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import Chamado, EventoChamado, ItemValor


class ItemValorInline(admin.TabularInline):  # type: ignore[type-arg]
    model = ItemValor
    extra = 0


class EventoChamadoInline(admin.TabularInline):  # type: ignore[type-arg]
    model = EventoChamado
    extra = 0
    can_delete = False
    readonly_fields = ("usuario", "de_status", "para_status", "dados", "criado_em")


@admin.register(Chamado)
class ChamadoAdmin(GISModelAdmin):
    list_display = ("id", "placa", "status", "cliente", "prestador", "valor_previsto", "criado_em")
    list_filter = ("status",)
    list_select_related = ("cliente", "prestador")
    search_fields = ("placa",)
    raw_id_fields = ("cliente", "atendente", "prestador")
    readonly_fields = ("rastreio_token", "version", "criado_em", "atualizado_em")
    inlines = (ItemValorInline, EventoChamadoInline)
    # Paginação do admin sem COUNT(*) completo em tabela grande.
    show_full_result_count = False
