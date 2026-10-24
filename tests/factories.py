from decimal import Decimal

import factory
from django.contrib.gis.geos import Point

from apps.chamados.models import Chamado, Status
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


class ChamadoFactory(factory.django.DjangoModelFactory[Chamado]):
    """Chamado direto no status desejado (sem passar pelo cálculo de distância)."""

    class Meta:
        model = Chamado

    cliente = factory.SubFactory(ClienteFactory)
    atendente = factory.SubFactory(UsuarioFactory, papel=Papel.ATENDENTE)
    status = Status.ABERTO
    placa = "ABC1D23"
    endereco_origem = "Praça da Sé, São Paulo"
    origem = Point(-46.6339, -23.5503, srid=4326)
    destino = Point(-46.4731, -23.4356, srid=4326)
    distancia_km = Decimal("58.00")
    valor_previsto = Decimal("331.00")
