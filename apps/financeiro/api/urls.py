from django.urls import path

from . import views

urlpatterns = [
    path("fechamentos", views.FechamentoListaView.as_view(), name="fechamentos"),
    path("fechamentos/gerar", views.GerarFechamentosView.as_view(), name="fechamentos-gerar"),
    path("fechamentos/<int:pk>", views.FechamentoDetalheView.as_view(), name="fechamento-detalhe"),
]
