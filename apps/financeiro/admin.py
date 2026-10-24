from django.contrib import admin

from .models import Fechamento, FechamentoItem


class FechamentoItemInline(admin.TabularInline):  # type: ignore[type-arg]
    model = FechamentoItem
    extra = 0
    can_delete = False
    raw_id_fields = ("chamado",)
    readonly_fields = ("chamado", "valor")


@admin.register(Fechamento)
class FechamentoAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("id", "tipo", "cliente", "prestador", "periodo_inicio", "total", "status")
    list_filter = ("tipo", "status", "periodo_inicio")
    list_select_related = ("cliente", "prestador")
    readonly_fields = ("total", "quantidade_chamados", "criado_em")
    inlines = (FechamentoItemInline,)
