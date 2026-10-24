from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import Prestador


@admin.register(Prestador)
class PrestadorAdmin(GISModelAdmin):
    list_display = ("nome", "telefone", "disponivel", "atualizado_em")
    list_filter = ("disponivel",)
    search_fields = ("nome", "telefone")
    raw_id_fields = ("usuario",)
