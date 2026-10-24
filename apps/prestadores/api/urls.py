from django.urls import path

from .views import MinhaLocalizacaoView

urlpatterns = [
    path(
        "prestadores/me/localizacao",
        MinhaLocalizacaoView.as_view(),
        name="prestador-localizacao",
    ),
]
