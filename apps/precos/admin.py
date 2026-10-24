from django.contrib import admin

from .models import TabelaPrecos


@admin.register(TabelaPrecos)
class TabelaPrecosAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("nome", "valor_saida", "valor_km_excedente", "km_franquia", "atualizado_em")
    search_fields = ("nome",)
