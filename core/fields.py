from typing import Any

from django.contrib.gis.geos import Point
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


@extend_schema_field(
    {
        "type": "object",
        "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
        "required": ["lat", "lng"],
    }
)
class PontoField(serializers.Field):  # type: ignore[type-arg]
    """`{"lat": -23.55, "lng": -46.63}` <-> `Point(lng, lat, srid=4326)`."""

    default_error_messages = {
        "invalido": "Informe um objeto com 'lat' e 'lng' numéricos.",
        "fora_do_intervalo": "Latitude deve estar entre -90 e 90; longitude entre -180 e 180.",
    }

    def to_internal_value(self, data: Any) -> Point:
        if not isinstance(data, dict):
            self.fail("invalido")
        try:
            lat, lng = float(data["lat"]), float(data["lng"])
        except (KeyError, TypeError, ValueError):
            self.fail("invalido")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            self.fail("fora_do_intervalo")
        return Point(lng, lat, srid=4326)

    def to_representation(self, value: Point) -> dict[str, float]:
        return {"lat": value.y, "lng": value.x}
