from django.urls import path

from . import views

urlpatterns = [
    path("chamados", views.ChamadoListaView.as_view(), name="chamados"),
    path("chamados/<int:pk>", views.ChamadoDetalheView.as_view(), name="chamado-detalhe"),
    path("chamados/<int:pk>/aceitar", views.AceitarView.as_view(), name="chamado-aceitar"),
    path("chamados/<int:pk>/recusar", views.RecusarView.as_view(), name="chamado-recusar"),
    path("chamados/<int:pk>/status", views.AvancarView.as_view(), name="chamado-status"),
    path("chamados/<int:pk>/concluir", views.ConcluirView.as_view(), name="chamado-concluir"),
    path("chamados/<int:pk>/cancelar", views.CancelarView.as_view(), name="chamado-cancelar"),
]
