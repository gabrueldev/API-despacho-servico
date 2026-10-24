from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class Papel(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    ATENDENTE = "ATENDENTE", "Atendente"
    DESPACHANTE = "DESPACHANTE", "Despachante"
    PRESTADOR = "PRESTADOR", "Prestador"
    FINANCEIRO = "FINANCEIRO", "Financeiro"


class UsuarioManager(BaseUserManager["Usuario"]):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> "Usuario":
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> "Usuario":
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("papel", Papel.ADMIN)
        return self.create_user(email, password, **extra)


class Usuario(AbstractUser):
    username = None  # type: ignore[assignment]
    email = models.EmailField("e-mail", unique=True)
    papel = models.CharField(max_length=20, choices=Papel.choices)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects = UsuarioManager()  # type: ignore[assignment,misc]

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self) -> str:
        return self.email
