from django.urls import path

from .views import ChamadoDetalheView, ChamadoListaView

urlpatterns = [
    path("chamados", ChamadoListaView.as_view(), name="chamados"),
    path("chamados/<int:pk>", ChamadoDetalheView.as_view(), name="chamado-detalhe"),
]
