from django.db import migrations, models


class Migration(migrations.Migration):
    """Renomeia coluna e índices só em metadados (sem reconstruir índice).

    No Postgres, renomear a coluna já atualiza os índices que a usam; aqui o
    banco recebe só RENAMEs e o estado do Django troca a definição dos índices.
    """

    dependencies = [
        ("chamados", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RenameField(
                    model_name="chamado", old_name="concluido_em", new_name="encerrado_em"
                ),
                migrations.RunSQL(
                    "ALTER INDEX chamado_cliente_concluido RENAME TO chamado_cliente_encerrado;"
                    "ALTER INDEX chamado_prestador_concluido RENAME TO chamado_prestador_encerrado;",
                    reverse_sql=(
                        "ALTER INDEX chamado_cliente_encerrado RENAME TO chamado_cliente_concluido;"
                        "ALTER INDEX chamado_prestador_encerrado RENAME TO chamado_prestador_concluido;"
                    ),
                ),
            ],
            state_operations=[
                migrations.RemoveIndex(model_name="chamado", name="chamado_cliente_concluido"),
                migrations.RemoveIndex(model_name="chamado", name="chamado_prestador_concluido"),
                migrations.RenameField(
                    model_name="chamado", old_name="concluido_em", new_name="encerrado_em"
                ),
                migrations.AddIndex(
                    model_name="chamado",
                    index=models.Index(
                        fields=["cliente", "encerrado_em"], name="chamado_cliente_encerrado"
                    ),
                ),
                migrations.AddIndex(
                    model_name="chamado",
                    index=models.Index(
                        fields=["prestador", "encerrado_em"], name="chamado_prestador_encerrado"
                    ),
                ),
            ],
        ),
    ]
