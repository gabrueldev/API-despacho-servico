from django.db import models


class TipoItem(models.TextChoices):
    SAIDA = "SAIDA", "Saída"
    KM_EXCEDENTE = "KM_EXCEDENTE", "Km excedente"
    PEDAGIO = "PEDAGIO", "Pedágio"
    ESPERA = "ESPERA", "Espera"
    ADICIONAL = "ADICIONAL", "Adicional"
    TAXA_CANCELAMENTO = "TAXA_CANCELAMENTO", "Taxa de cancelamento"
