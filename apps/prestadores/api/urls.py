from django.urls import path

from .views import MeuPerfilView, MinhaLocalizacaoView, ProximosView

urlpatterns = [
    path("prestadores/proximos", ProximosView.as_view(), name="prestadores-proximos"),
    path("prestadores/me", MeuPerfilView.as_view(), name="prestador-me"),
    path(
        "prestadores/me/localizacao",
        MinhaLocalizacaoView.as_view(),
        name="prestador-localizacao",
    ),
]
