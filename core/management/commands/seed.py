"""Dados de demonstração: `python manage.py seed [--chamados N] [--prestadores N] [--limpar]`.

Determinístico (semente fixa) e rápido: tudo em `bulk_create`, um único hash de senha para
todos os usuários e as datas espalhadas por um UPDATE no banco.
"""

import math
import random
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction
from django.utils import timezone

from apps.chamados.models import Chamado, EventoChamado, ItemValor, Status
from apps.clientes.models import Cliente
from apps.contas.models import Papel, Usuario
from apps.financeiro import services as financeiro
from apps.financeiro.models import Fechamento, FechamentoItem
from apps.precos import calculo
from apps.precos.models import TabelaPrecos
from apps.precos.tipos import TipoItem
from apps.prestadores import localizacao
from apps.prestadores.models import Prestador
from core.models import IdempotencyKey

SENHA_DEMO = "despacha123"
DOMINIO = "despacha.dev"
CENTRO = (-23.5503, -46.6339)  # Praça da Sé, São Paulo
LOTE = 2000

# Proporção de cada status entre os chamados gerados.
DISTRIBUICAO = {
    Status.CONCLUIDO: 0.75,
    Status.CANCELADO: 0.08,
    Status.ABERTO: 0.05,
    Status.A_CAMINHO: 0.03,
    Status.EM_ATENDIMENTO: 0.03,
    Status.DESPACHADO: 0.02,
    Status.ACEITO: 0.02,
    Status.NO_LOCAL: 0.02,
}
ATIVOS = (
    Status.DESPACHADO,
    Status.ACEITO,
    Status.A_CAMINHO,
    Status.NO_LOCAL,
    Status.EM_ATENDIMENTO,
)
ENDERECOS = ("Av. Paulista", "Rua Augusta", "Av. Rebouças", "Marginal Tietê", "Av. do Estado")


def _km_linha_reta(a: Point, b: Point) -> Decimal:
    """Haversine em Python: o mesmo que a API grava com `LINHA_RETA`, sem uma query por chamado
    (a diferença para o elipsoide do PostGIS fica abaixo de 0,5%)."""
    lat1, lat2 = math.radians(a.y), math.radians(b.y)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b.x - a.x) / 2) ** 2
    )
    return Decimal(2 * 6371.0088 * math.asin(math.sqrt(h))).quantize(Decimal("0.01"))


class Command(BaseCommand):
    help = "Cria dados de demonstração (só com DJANGO_DEBUG=true, ou --forcar)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--chamados", type=int, default=2000)
        parser.add_argument("--prestadores", type=int, default=150)
        parser.add_argument(
            "--limpar", action="store_true", help="Apaga os dados do domínio antes."
        )
        parser.add_argument("--forcar", action="store_true", help="Permite rodar com DEBUG=false.")

    def handle(self, *args: Any, **opcoes: Any) -> None:
        if not settings.DEBUG and not opcoes["forcar"]:
            raise CommandError("Recusado com DEBUG=false. Use --forcar se tiver certeza.")
        if opcoes["limpar"]:
            self._limpar()
        elif Usuario.objects.filter(email=f"admin@{DOMINIO}").exists():
            self.stdout.write("Dados de demonstração já existem. Use --limpar para recriar.")
            return
        if opcoes["prestadores"] < 1 or opcoes["chamados"] < 0:
            raise CommandError("Use --prestadores >= 1 e --chamados >= 0.")

        rng = random.Random(42)  # noqa: S311 — dados de demonstração, não segredo
        with transaction.atomic():
            equipe = self._equipe()
            tabelas = self._tabelas()
            clientes = self._clientes(tabelas)
            prestadores = self._prestadores(rng, opcoes["prestadores"])
            ativos = self._chamados(rng, opcoes["chamados"], equipe, clientes, prestadores)
            fechamentos = self._fechamentos()
        self._posicoes_no_redis(ativos)
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE")  # estatísticas do planner em dia para o EXPLAIN

        self._resumo(fechamentos)

    # --- etapas ----------------------------------------------------------------------------

    def _limpar(self) -> None:
        tabelas = [
            m._meta.db_table
            for m in (
                FechamentoItem,
                Fechamento,
                EventoChamado,
                ItemValor,
                Chamado,
                Prestador,
                Cliente,
                TabelaPrecos,
                IdempotencyKey,
            )
        ]
        with connection.cursor() as cursor:
            # FKs do Django são DEFERRABLE: dentro de uma transação com inserts pendentes
            # (ex.: testes) o TRUNCATE recusaria sem antes checar as constraints.
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(f"TRUNCATE {', '.join(tabelas)} RESTART IDENTITY CASCADE")
        Usuario.objects.filter(email__endswith=f"@{DOMINIO}").delete()
        self.stdout.write("Dados anteriores apagados.")

    def _equipe(self) -> dict[Papel, Usuario]:
        senha = make_password(SENHA_DEMO)
        equipe = {
            papel: Usuario(email=f"{nome}@{DOMINIO}", papel=papel, password=senha)
            for papel, nome in (
                (Papel.ADMIN, "admin"),
                (Papel.ATENDENTE, "atendente"),
                (Papel.DESPACHANTE, "despachante"),
                (Papel.FINANCEIRO, "financeiro"),
            )
        }
        equipe[Papel.ADMIN].is_staff = equipe[Papel.ADMIN].is_superuser = True
        Usuario.objects.bulk_create(equipe.values())
        return equipe

    def _tabelas(self) -> list[TabelaPrecos]:
        return TabelaPrecos.objects.bulk_create(
            [
                TabelaPrecos(
                    nome="Padrão",
                    valor_saida=Decimal("250.00"),
                    valor_km_excedente=Decimal("4.50"),
                    km_franquia=Decimal(40),
                    valor_hora_espera=Decimal("60.00"),
                ),
                TabelaPrecos(
                    nome="Premium",
                    valor_saida=Decimal("320.00"),
                    valor_km_excedente=Decimal("5.20"),
                    km_franquia=Decimal(50),
                    valor_hora_espera=Decimal("75.00"),
                ),
            ]
        )

    def _clientes(self, tabelas: list[TabelaPrecos]) -> list[Cliente]:
        nomes = ("Proteção Veicular Alfa", "Associação Beta", "Clube Gama Auto")
        return Cliente.objects.bulk_create(
            Cliente(nome=nome, cnpj=f"{i + 1:02d}{'0' * 12}", tabela_precos=tabelas[i % 2])
            for i, nome in enumerate(nomes)
        )

    def _prestadores(self, rng: random.Random, n: int) -> list[Prestador]:
        senha = make_password(SENHA_DEMO)
        usuarios = Usuario.objects.bulk_create(
            Usuario(email=f"prestador{i}@{DOMINIO}", papel=Papel.PRESTADOR, password=senha)
            for i in range(1, n + 1)
        )
        return Prestador.objects.bulk_create(
            (
                Prestador(
                    usuario=u,
                    nome=f"Guincho {i:03d}",
                    telefone=f"119{rng.randint(10_000_000, 99_999_999)}",
                    disponivel=rng.random() < 0.6,
                    localizacao=Point(
                        CENTRO[1] + rng.uniform(-0.4, 0.4),
                        CENTRO[0] + rng.uniform(-0.35, 0.35),
                        srid=4326,
                    ),
                )
                for i, u in enumerate(usuarios, start=1)
            ),
            batch_size=LOTE,
        )

    def _chamados(
        self,
        rng: random.Random,
        n: int,
        equipe: dict[Papel, Usuario],
        clientes: list[Cliente],
        prestadores: list[Prestador],
    ) -> list[tuple[Chamado, Prestador]]:
        statuses = rng.choices(list(DISTRIBUICAO), weights=list(DISTRIBUICAO.values()), k=n)
        # Cada prestador atende no máximo um chamado em andamento, e até 40% ficam ocupados,
        # para sobrar gente disponível na busca por proximidade.
        livres = rng.sample(prestadores, k=len(prestadores) * 2 // 5)
        tabela_por_cliente = {c.pk: c.tabela_precos.dados() for c in clientes}

        chamados: list[Chamado] = []
        itens: list[list[calculo.ItemCalculado]] = []
        ativos: list[tuple[Chamado, Prestador]] = []
        for status in statuses:
            if status in ATIVOS and not livres:
                status = Status.CONCLUIDO
            cliente = rng.choice(clientes)
            tabela = tabela_por_cliente[cliente.pk]
            origem = Point(
                CENTRO[1] + rng.uniform(-0.3, 0.3), CENTRO[0] + rng.uniform(-0.3, 0.3), srid=4326
            )
            destino = Point(
                origem.x + rng.uniform(-0.45, 0.45), origem.y + rng.uniform(-0.45, 0.45), srid=4326
            )
            distancia = _km_linha_reta(origem, destino)
            previstos = calculo.itens_deslocamento(tabela, distancia)
            valor_previsto = calculo.total(previstos)

            prestador = None
            valor_final = None
            if status in ATIVOS:
                prestador = livres.pop()
            elif status != Status.ABERTO:
                prestador = rng.choice(prestadores)
            if status == Status.CONCLUIDO:
                valor_final = valor_previsto
            elif status == Status.CANCELADO:
                com_taxa = rng.random() < 0.5
                valor_final = tabela.valor_saida if com_taxa else Decimal("0.00")
                if com_taxa:
                    previstos = [
                        calculo.ItemCalculado(
                            TipoItem.TAXA_CANCELAMENTO,
                            "Taxa de saída",
                            Decimal(1),
                            tabela.valor_saida,
                        )
                    ]

            chamado = Chamado(
                cliente=cliente,
                atendente=equipe[Papel.ATENDENTE],
                prestador=prestador,
                status=status,
                placa=f"{''.join(rng.choices('ABCDEFGHJKLMNPRSTUVWXYZ', k=3))}"
                f"{rng.randint(0, 9)}{rng.choice('ABCDEFGHJ0123456789')}{rng.randint(10, 99)}",
                endereco_origem=f"{rng.choice(ENDERECOS)}, {rng.randint(1, 3000)}",
                origem=origem,
                destino=destino,
                distancia_km=distancia,
                valor_previsto=valor_previsto,
                valor_final=valor_final,
            )
            chamados.append(chamado)
            itens.append(previstos)
            if prestador and status in ATIVOS:
                ativos.append((chamado, prestador))

        Chamado.objects.bulk_create(chamados, batch_size=LOTE)
        ItemValor.objects.bulk_create(
            (
                ItemValor(
                    chamado=c,
                    tipo=i.tipo,
                    descricao=i.descricao,
                    quantidade=i.quantidade,
                    valor_unitario=i.valor_unitario,
                    total=i.total,
                )
                for c, lista in zip(chamados, itens, strict=True)
                for i in lista
            ),
            batch_size=LOTE,
        )
        EventoChamado.objects.bulk_create(
            (
                EventoChamado(
                    chamado=c,
                    usuario=equipe[Papel.ATENDENTE],
                    de_status=None,
                    para_status=Status.ABERTO,
                )
                for c in chamados
            ),
            batch_size=LOTE,
        )
        Prestador.objects.filter(pk__in=[p.pk for _, p in ativos]).update(disponivel=False)
        self._espalhar_datas()
        return ativos

    def _espalhar_datas(self) -> None:
        """Encerrados nos últimos 6 meses (fecham horas depois); em aberto, nas últimas 3h."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT setseed(0.42)")
            cursor.execute(
                f"""
                UPDATE {Chamado._meta.db_table}
                SET criado_em = now() - random() * CASE WHEN status IN (%s, %s)
                    THEN interval '180 days' ELSE interval '3 hours' END
                """,  # noqa: S608
                [Status.CONCLUIDO, Status.CANCELADO],
            )
            cursor.execute(
                f"""
                UPDATE {Chamado._meta.db_table}
                SET encerrado_em = LEAST(criado_em + (1 + random() * 5) * interval '1 hour', now())
                WHERE status IN (%s, %s)
                """,  # noqa: S608
                [Status.CONCLUIDO, Status.CANCELADO],
            )
            # Como nos services: concluído vale por RASTREIO_VALIDADE_HORAS; cancelado expira já.
            cursor.execute(
                f"""
                UPDATE {Chamado._meta.db_table}
                SET rastreio_expira_em = encerrado_em
                    + CASE WHEN status = %s THEN %s * interval '1 hour' ELSE interval '0' END
                WHERE encerrado_em IS NOT NULL
                """,  # noqa: S608
                [Status.CONCLUIDO, settings.RASTREIO_VALIDADE_HORAS],
            )

    def _fechamentos(self) -> int:
        """Fecha os meses já encerrados cobertos pelos dados."""
        hoje = timezone.localdate()
        total = 0
        ano, mes = hoje.year, hoje.month
        for _ in range(6):
            mes -= 1
            if mes == 0:
                ano, mes = ano - 1, 12
            resultado = financeiro.gerar(financeiro.Periodo.mes(ano, mes))
            total += sum(r.fechamentos for r in resultado.values())
        return total

    def _posicoes_no_redis(self, ativos: list[tuple[Chamado, Prestador]]) -> None:
        for _, prestador in ativos:
            if prestador.localizacao:
                localizacao.registrar(
                    prestador.usuario_id, prestador.localizacao.y, prestador.localizacao.x
                )

    def _resumo(self, fechamentos: int) -> None:
        exemplo = (
            Chamado.objects.filter(status=Status.A_CAMINHO)
            .values_list("rastreio_token", flat=True)
            .first()
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Criados: {Chamado.objects.count()} chamados, "
                f"{Prestador.objects.count()} prestadores, "
                f"{Cliente.objects.count()} clientes e {fechamentos} fechamentos."
            )
        )
        self.stdout.write(
            f"Login (senha {SENHA_DEMO}): admin@, atendente@, despachante@, financeiro@ "
            f"e prestador1@ … @{DOMINIO}"
        )
        if exemplo:
            self.stdout.write(f"Acompanhamento de exemplo (front): /acompanhar/{exemplo}")
