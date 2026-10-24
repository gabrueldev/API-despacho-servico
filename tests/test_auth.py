import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.contas.models import Papel, Usuario


@pytest.mark.django_db
def test_login_retorna_access_e_refresh() -> None:
    Usuario.objects.create_user("atendente@despacha.dev", "senha-forte-123", papel=Papel.ATENDENTE)

    response = APIClient().post(
        reverse("login"),
        {"email": "atendente@despacha.dev", "password": "senha-forte-123"},
        format="json",
    )

    assert response.status_code == 200
    assert {"access", "refresh"} <= response.json().keys()


@pytest.mark.django_db
def test_login_com_senha_errada_retorna_401() -> None:
    Usuario.objects.create_user("atendente@despacha.dev", "senha-forte-123", papel=Papel.ATENDENTE)

    response = APIClient().post(
        reverse("login"),
        {"email": "atendente@despacha.dev", "password": "errada"},
        format="json",
    )

    assert response.status_code == 401
