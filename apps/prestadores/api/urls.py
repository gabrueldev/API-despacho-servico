from django.urls import path

from .views import MinhaLocalizacaoView, ProximosView

urlpatterns = [
    path("prestadores/proximos", ProximosView.as_view(), name="prestadores-proximos"),
    path(
        "prestadores/me/localizacao",
        MinhaLocalizacaoView.as_view(),
        name="prestador-localizacao",
    ),
]
