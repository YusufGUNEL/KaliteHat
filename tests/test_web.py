import pytest

from kalitehat import create_app
from kalitehat.db import baglan


@pytest.fixture
def client(tmp_path):
    yol = str(tmp_path / "t.db")
    c = baglan(yol)
    c.execute("INSERT INTO parca (id, kod, ad, revizyon, malzeme) VALUES (1, 'P-100', 'Pim', 'A', '1.2842')")
    c.execute("INSERT INTO karakteristik (parca_id, no, ad, nominal, alt_sapma, ust_sapma, birim, alet_tipi, kritik)"
              " VALUES (1, 1, 'Çap', 12.0, 0.0, 0.018, 'mm', 'Mikrometre', 1)")
    c.execute("INSERT INTO alet (id, kod, ad, tip, kalibrasyon_bitis) VALUES (1, 'MK-01', 'Mik', 'Mikrometre', '2099-01-01')")
    c.execute("INSERT INTO alet (id, kod, ad, tip, kalibrasyon_bitis) VALUES (2, 'MK-02', 'Eski', 'Mikrometre', '2020-01-01')")
    c.commit()
    c.close()
    app = create_app(yol)
    app.testing = True
    return app.test_client()


def test_api_ile_is_emri_al_ve_kalite_oku(client):
    r = client.post("/api/is-emirleri", json=[{"is_emri_no": "IE-1", "parca_kodu": "P-100", "lot": "L1", "adet": 10},
                                              {"is_emri_no": "IE-2", "parca_kodu": "YOK", "lot": "L2", "adet": 5}])
    assert r.status_code == 201
    assert r.json["eklenen"] == ["IE-1"] and r.json["atlanan"][0]["is_emri_no"] == "IE-2"

    r = client.get("/api/is-emirleri/IE-1/kalite")
    assert r.json["durum"] == "FAI_BEKLIYOR" and r.json["sevke_uygun"] is False

    assert client.get("/api/is-emirleri/YOK/kalite").status_code == 404
    assert client.post("/api/is-emirleri", data="bozuk", content_type="application/json").status_code == 400


def test_form_akisi_ve_sayfalar(client):
    client.post("/api/is-emirleri", json={"is_emri_no": "IE-1", "parca_kodu": "P-100", "lot": "L1", "adet": 10})

    r = client.post("/is-emri/IE-1/muayene/FAI", data={"deger_1": "12,01", "alet_1": "2", "personel": "Ali"})
    assert "kalibrasyonu" in r.get_data(as_text=True)

    r = client.post("/is-emri/IE-1/muayene/FAI", data={"deger_1": "12,03", "alet_1": "1", "personel": "Ali"})
    assert r.status_code == 302
    assert client.get("/api/is-emirleri/IE-1/kalite").json["durum"] == "KARANTINA"

    r = client.post("/uygunsuzluk/1", data={"kok_neden": "Ofset", "aksiyon": "Düzeltildi", "sorumlu": "Veli",
                                            "karar": "YENIDEN_ISLEME"})
    assert r.status_code == 302

    for yol in ["/", "/is-emirleri", "/is-emirleri?durum=KARANTINA", "/is-emri/IE-1", "/is-emri/IE-1/muayene/FAI",
                "/uygunsuzluklar", "/uygunsuzluk/1", "/parcalar", "/aletler", "/spc/1", "/izlenebilirlik?q=L1",
                "/api/kalite-durumlari"]:
        assert client.get(yol).status_code == 200, yol
    assert client.get("/is-emri/YOK").status_code == 404


def test_csv_yukleme(client):
    import io

    veri = "is_emri_no;parca_kodu;lot;adet\nIE-5;P-100;L5;7\n".encode("utf-8")
    r = client.post("/is-emirleri/ice-aktar", data={"dosya": (io.BytesIO(veri), "a.csv")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "1 iş emri alındı" in r.get_data(as_text=True)
