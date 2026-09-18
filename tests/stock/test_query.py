from __future__ import annotations

from tests.stock.helpers import stock_scene

from docprod.stock.query import generate_stock_queries


def test_queries_are_short_visual_english() -> None:
    scene = stock_scene(
        "scene_0001",
        "İstanbul'daki tren istasyonu akşam saatlerinde neredeyse boştu.",
    )
    queries = generate_stock_queries(scene)
    assert 2 <= len(queries) <= 4
    blob = " ".join(queries).lower()
    assert "train station" in blob or "railway" in blob
    assert "istanbul'daki tren istasyonu akşam" not in blob
    assert all(len(item.split()) <= 8 for item in queries)


def test_station_exit_and_phone_queries() -> None:
    scene = stock_scene(
        "scene_0007",
        "İstasyonun kuzey çıkışına doğru koşarak gitti, telefonunu açtı.",
        category="action",
    )
    queries = generate_stock_queries(scene)
    blob = " ".join(queries).lower()
    assert "station" in blob
    assert "phone" in blob or "walking" in blob or "exit" in blob


def test_car_braking_queries() -> None:
    scene = stock_scene(
        "scene_0014",
        "Araba istasyon önünde ani fren yaptı.",
        category="vehicle",
    )
    queries = generate_stock_queries(scene)
    blob = " ".join(queries).lower()
    assert "car" in blob
    assert "brak" in blob or "stop" in blob
