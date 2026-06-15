"""El `latest` del SPI debe ser el último punto CON spi interpretable; si ningún
punto tiene spi real, debe ser None (no un punto con spi=None, que es
ininterpretable y confundía a los consumidores)."""

from app.routers.analytics import _spi_latest


def test_latest_es_el_ultimo_con_spi_real():
    points = [
        {"month": "2020-01", "spi": -0.4, "category": "Normal"},
        {"month": "2020-02", "spi": 1.1, "category": "Moderadamente húmedo"},
        {"month": "2020-03", "spi": None, "category": "No calculable"},
    ]
    assert _spi_latest(points)["month"] == "2020-02"


def test_latest_none_cuando_ningun_punto_tiene_spi():
    points = [
        {"month": "2020-01", "spi": None, "category": "No calculable"},
        {"month": "2020-02", "spi": None, "category": "No calculable"},
    ]
    assert _spi_latest(points) is None


def test_latest_none_con_lista_vacia():
    assert _spi_latest([]) is None
