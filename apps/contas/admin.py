from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):  # type: ignore[type-arg]
    ordering = ("email",)
    list_display = ("email", "papel", "is_active", "is_staff")
    list_filter = ("papel", "is_active", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados", {"fields": ("first_name", "last_name", "papel")}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Datas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "papel", "password1", "password2")}),
    )
