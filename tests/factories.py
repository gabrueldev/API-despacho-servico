from decimal import Decimal

import factory
from django.contrib.gis.geos import Point

from apps.clientes.models import Cliente
from apps.contas.models import Papel, Usuario
from apps.precos.models import TabelaPrecos
from apps.prestadores.models import Prestador


class UsuarioFactory(factory.django.DjangoModelFactory[Usuario]):
    class Meta:
        model = Usuario
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"usuario{n}@despacha.dev")
    papel = Papel.ATENDENTE
    password = factory.django.Password("senha-forte-123")


class TabelaPrecosFactory(factory.django.DjangoModelFactory[TabelaPrecos]):
    class Meta:
        model = TabelaPrecos

    nome = factory.Sequence(lambda n: f"Tabela {n}")
    valor_saida = Decimal("250.00")
    valor_km_excedente = Decimal("4.50")
    km_franquia = Decimal("40")
    valor_hora_espera = Decimal("60.00")


class ClienteFactory(factory.django.DjangoModelFactory[Cliente]):
    class Meta:
        model = Cliente

    nome = factory.Sequence(lambda n: f"Proteção Veicular {n}")
    cnpj = factory.Sequence(lambda n: f"{n:014d}")
    tabela_precos = factory.SubFactory(TabelaPrecosFactory)


class PrestadorFactory(factory.django.DjangoModelFactory[Prestador]):
    class Meta:
        model = Prestador

    usuario = factory.SubFactory(UsuarioFactory, papel=Papel.PRESTADOR)
    nome = factory.Sequence(lambda n: f"Guincho {n}")
    telefone = "11999990000"
    disponivel = True
    localizacao = Point(-46.63, -23.55, srid=4326)
