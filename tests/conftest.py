import pytest

from kalitehat import create_app, kullanicilar
from kalitehat.db import baglan


def tohumla(c):
    c.execute("INSERT INTO parca (id, kod, ad, revizyon, malzeme) VALUES (1, 'P-100', 'Pim', 'A', '1.2842')")
    c.executemany(
        "INSERT INTO karakteristik (id, parca_id, no, ad, nominal, alt_sapma, ust_sapma, birim, alet_tipi, kritik)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(1, 1, 1, "Çap", 12.0, 0.0, 0.018, "mm", "Mikrometre", 1),
         (2, 1, 2, "Boy", 40.0, -0.1, 0.1, "mm", "Kumpas", 0)],
    )
    c.executemany(
        "INSERT INTO alet (id, kod, ad, tip, kalibrasyon_bitis) VALUES (?,?,?,?,?)",
        [(1, "MK-01", "Mikrometre 0-25", "Mikrometre", "2099-01-01"),
         (2, "KP-01", "Kumpas 150", "Kumpas", "2099-01-01"),
         (3, "MK-02", "Mikrometre eski", "Mikrometre", "2020-01-01")],
    )
    c.execute("INSERT INTO is_emri (no, parca_id, lot, adet, olusturma) VALUES ('IE-1', 1, 'L-1', 50, '2026-11-13 00:00')")
    c.commit()
    kullanicilar.ekle(c, "op", "Ali Operatör", "OPERATOR", "demo")
    kullanicilar.ekle(c, "kal", "Kalite Kişisi", "KALITE", "demo")
    kullanicilar.ekle(c, "yon", "Yönetici Kişi", "YONETICI", "demo")


@pytest.fixture
def conn():
    c = baglan(":memory:")
    tohumla(c)
    return c


def olc(cap, boy, cap_alet=1):
    return [{"karakteristik_id": 1, "deger": cap, "alet_id": cap_alet},
            {"karakteristik_id": 2, "deger": boy, "alet_id": 2}]


@pytest.fixture
def app(tmp_path):
    yol = str(tmp_path / "t.db")
    c = baglan(yol)
    tohumla(c)
    c.close()
    a = create_app({"DB": yol, "TESTING": True, "API_ANAHTARI": "test-anahtar", "SECRET_KEY": "test"})
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_al(client):
    """Bir sayfa açıp oturumdaki CSRF jetonunu döndürür."""
    client.get("/giris")
    with client.session_transaction() as s:
        return s["csrf"]


def giris_yap(client, kullanici="kal"):
    jeton = csrf_al(client)
    r = client.post("/giris", data={"kullanici_adi": kullanici, "parola": "demo", "csrf": jeton})
    assert r.status_code == 302
    with client.session_transaction() as s:
        return s["csrf"]
