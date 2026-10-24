from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTStatelessUserScheme


class JWTSemEstadoScheme(SimpleJWTStatelessUserScheme):  # type: ignore[no-untyped-call]
    """Mesmo Bearer JWT, nome próprio no OpenAPI (o contrib reusa "jwtAuth" e colide)."""

    name = "jwtSemEstado"
    priority = 1
