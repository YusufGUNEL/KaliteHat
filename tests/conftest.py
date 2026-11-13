import pytest

from kalitehat.db import baglan


@pytest.fixture
def conn():
    c = baglan(":memory:")
    c.execute("INSERT INTO parca (id, kod, ad, revizyon, malzeme) VALUES (1, 'P-100', 'Pim', 'A', '1.2842')")
    c.executemany(
        "INSERT INTO karakteristik (id, parca_id, no, ad, nominal, alt_sapma, ust_sapma, birim, alet_tipi, kritik)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (1, 1, 1, "Çap", 12.0, 0.0, 0.018, "mm", "Mikrometre", 1),
            (2, 1, 2, "Boy", 40.0, -0.1, 0.1, "mm", "Kumpas", 0),
        ],
    )
    c.executemany(
        "INSERT INTO alet (id, kod, ad, tip, kalibrasyon_bitis) VALUES (?,?,?,?,?)",
        [
            (1, "MK-01", "Mikrometre 0-25", "Mikrometre", "2099-01-01"),
            (2, "KP-01", "Kumpas 150", "Kumpas", "2099-01-01"),
            (3, "MK-02", "Mikrometre eski", "Mikrometre", "2020-01-01"),
        ],
    )
    c.execute(
        "INSERT INTO is_emri (no, parca_id, lot, adet, olusturma) VALUES ('IE-1', 1, 'L-1', 50, '2026-11-13 00:00')"
    )
    c.commit()
    return c


def olc(cap, boy, cap_alet=1):
    return [
        {"karakteristik_id": 1, "deger": cap, "alet_id": cap_alet},
        {"karakteristik_id": 2, "deger": boy, "alet_id": 2},
    ]
