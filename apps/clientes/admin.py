from django.contrib import admin

from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("nome", "cnpj", "tabela_precos", "ativo")
    list_select_related = ("tabela_precos",)
    list_filter = ("ativo",)
    search_fields = ("nome", "cnpj")
