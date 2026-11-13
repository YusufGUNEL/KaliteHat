"""HTTP katmanı: API sözleşmesi, oturum, CSRF, roller ve uçtan uca akış."""
import io

from conftest import csrf_al, giris_yap
from openpyxl import load_workbook

API = {"X-API-Key": "test-anahtar"}


# ---------- API ----------

def test_api_anahtarsiz_reddedilir(client):
    r = client.get("/api/v1/is-emirleri")
    assert r.status_code == 401 and r.json["hata"]["kod"] == "YETKISIZ"
    assert client.get("/api/v1/is-emirleri", headers={"X-API-Key": "yanlis"}).status_code == 401
    assert client.get("/api/v1/openapi.json").status_code == 200  # sözleşme açık


def test_api_is_emri_al_listele_ve_kalite_oku(client):
    r = client.post("/api/v1/is-emirleri", headers=API,
                    json=[{"is_emri_no": "IE-10", "parca_kodu": "P-100", "lot": "L10", "adet": 10},
                          {"is_emri_no": "IE-11", "parca_kodu": "YOK", "lot": "L11", "adet": 5}])
    assert r.status_code == 201
    assert r.json["eklenen"] == ["IE-10"] and r.json["atlanan"][0]["is_emri_no"] == "IE-11"

    # aynı istek tekrar: çift kayıt yok, 200
    r = client.post("/api/v1/is-emirleri", headers=API,
                    json={"is_emri_no": "IE-10", "parca_kodu": "P-100", "lot": "L10", "adet": 10})
    assert r.status_code == 200 and r.json["eklenen"] == []

    r = client.get("/api/v1/is-emirleri/IE-10", headers=API)
    assert r.json["durum"] == "FAI_BEKLIYOR" and r.json["sevke_uygun"] is False

    r = client.get("/api/v1/is-emirleri?boyut=1&sayfa=2", headers=API)
    assert r.json["sayfalama"] == {"sayfa": 2, "boyut": 1, "toplam": 2, "sayfa_sayisi": 2}
    assert len(r.json["veri"]) == 1

    assert client.get("/api/v1/is-emirleri/YOK", headers=API).json["hata"]["kod"] == "BULUNAMADI"
    assert client.post("/api/v1/is-emirleri", headers=API, data="bozuk",
                       content_type="application/json").status_code == 400
    assert client.get("/api/v1/is-emirleri?sayfa=x", headers=API).status_code == 400


# ---------- oturum ve güvenlik ----------

def test_girissiz_yonlendirilir_ve_yanlis_parola(client):
    r = client.get("/")
    assert r.status_code == 302 and "/giris" in r.headers["Location"]
    jeton = csrf_al(client)
    r = client.post("/giris", data={"kullanici_adi": "kal", "parola": "yanlis", "csrf": jeton})
    assert "yanlış" in r.get_data(as_text=True)


def test_csrf_jetonu_olmadan_post_reddedilir(client):
    giris_yap(client)
    r = client.post("/is-emri/IE-1/muayene/FAI", data={"deger_1": "12.01"})
    assert r.status_code == 400


def test_acik_yonlendirme_engellenir(client):
    jeton = csrf_al(client)
    r = client.post("/giris?sonra=//kotu.example", data={"kullanici_adi": "kal", "parola": "demo", "csrf": jeton})
    assert r.headers["Location"] == "/"
    jeton = csrf_al(client)
    r = client.post("/giris?sonra=/%5Ckotu.example", data={"kullanici_adi": "kal", "parola": "demo", "csrf": jeton})
    assert r.headers["Location"] == "/"


def test_fai_raporunda_erp_verisi_formul_olmaz(client, app):
    from kalitehat.db import baglan

    conn = baglan(app.config["DB"])
    conn.execute("UPDATE is_emri SET lot = '=HYPERLINK(\"http://x\")' WHERE no = 'IE-1'")
    conn.commit()
    jeton = giris_yap(client, "kal")
    client.post("/is-emri/IE-1/muayene/FAI",
                data={"deger_1": "12,01", "alet_1": "1", "deger_2": "40", "alet_2": "2", "csrf": jeton})
    ws = load_workbook(io.BytesIO(client.get("/is-emri/IE-1/fai.xlsx").data)).active
    assert ws["B9"].data_type == "s"


def test_operator_dof_kapatamaz(client):
    jeton = giris_yap(client, "op")
    client.post("/is-emri/IE-1/muayene/FAI",
                data={"deger_1": "12,05", "alet_1": "1", "deger_2": "40", "alet_2": "2", "csrf": jeton})
    r = client.post("/uygunsuzluk/1", data={"kok_neden": "a", "aksiyon": "b", "sorumlu": "c",
                                            "karar": "YENIDEN_ISLEME", "csrf": jeton})
    assert r.status_code == 403


# ---------- uçtan uca ----------

def test_uctan_uca_akis_ve_tum_sayfalar(client):
    jeton = giris_yap(client, "kal")

    r = client.post("/is-emri/IE-1/muayene/FAI",
                    data={"deger_1": "12,01", "alet_1": "3", "deger_2": "40", "alet_2": "2", "csrf": jeton})
    assert "kalibrasyonu" in r.get_data(as_text=True)

    r = client.post("/is-emri/IE-1/muayene/FAI",
                    data={"deger_1": "12,03", "alet_1": "1", "deger_2": "40", "alet_2": "2", "csrf": jeton})
    assert r.status_code == 302
    assert client.get("/api/v1/is-emirleri/IE-1", headers=API).json["durum"] == "KARANTINA"

    r = client.post("/uygunsuzluk/1", data={"kok_neden": "Ofset", "aksiyon": "Düzeltildi", "sorumlu": "Veli",
                                            "karar": "YENIDEN_ISLEME", "csrf": jeton})
    assert r.status_code == 302

    r = client.post("/is-emri/IE-1/muayene/FAI",
                    data={"deger_1": "12,009", "alet_1": "1", "deger_2": "40", "alet_2": "2", "csrf": jeton})
    r = client.get("/is-emri/IE-1/fai.xlsx")
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.data)).active
    assert "FAI" in ws["A1"].value
    assert (ws["A11"].value, ws["B11"].value) == ("Muayene eden", "Kalite Kişisi")
    assert ws["B12"].value == "KABUL"

    denetim = client.get("/denetim").get_data(as_text=True)
    assert "Kalite Kişisi" in denetim and "DOF_KAPATILDI" in denetim

    for yol in ["/", "/is-emirleri", "/is-emirleri?durum=KARANTINA", "/is-emri/IE-1", "/is-emri/IE-1/muayene/PROSES",
                "/uygunsuzluklar", "/uygunsuzluk/1", "/parcalar", "/aletler", "/spc/1",
                "/izlenebilirlik?q=L-1", "/entegrasyon", "/api-belgesi", "/denetim"]:
        assert client.get(yol).status_code == 200, yol
    assert client.get("/is-emri/YOK").status_code == 404
    assert client.get("/spc").headers["Location"].endswith("/spc/1")


def test_csv_yukleme_ve_rol(client):
    jeton = giris_yap(client, "op")
    veri = b"is_emri_no;parca_kodu;lot;adet\nIE-5;P-100;L5;7\n"
    r = client.post("/is-emirleri/ice-aktar", data={"dosya": (io.BytesIO(veri), "a.csv"), "csrf": jeton},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "yetkiniz yok" in r.get_data(as_text=True)

    client.post("/cikis", data={"csrf": jeton})
    jeton = giris_yap(client, "kal")
    r = client.post("/is-emirleri/ice-aktar", data={"dosya": (io.BytesIO(veri), "a.csv"), "csrf": jeton},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "1 iş emri alındı" in r.get_data(as_text=True)


def test_olaylar_demo_erpye_gider_ve_tekrar_islenmez(client, app):
    jeton = giris_yap(client, "yon")
    client.post("/is-emri/IE-1/muayene/FAI",
                data={"deger_1": "12,01", "alet_1": "1", "deger_2": "40", "alet_2": "2", "csrf": jeton})

    # webhook'u test istemcisine yönlendir (gerçek HTTP yerine)
    from kalitehat import olaylar
    from kalitehat.db import baglan

    def test_gonderici(url, govde, anahtar, api):
        r = client.post("/demo-erp/webhook", json=govde, headers={"Idempotency-Key": anahtar, "X-API-Key": api})
        assert r.status_code == 200

    conn = baglan(app.config["DB"])
    assert olaylar.gonder_bekleyenler(conn, "x", test_gonderici, api_anahtari="test-anahtar")["gonderilen"] == 1
    olaylar.yeniden_kuyruga_al(conn, 1)  # VAZGECILDI/HATA değil → değişmez
    conn.execute("UPDATE olay SET durum='HATA', sonraki_deneme='2000-01-01 00:00'")
    conn.commit()
    olaylar.gonder_bekleyenler(conn, "x", test_gonderici, api_anahtari="test-anahtar")  # aynı olay ikinci kez
    assert conn.execute("SELECT COUNT(*) FROM demo_erp_kutusu").fetchone()[0] == 1

    assert client.post("/demo-erp/webhook", json={"tur": "x"}).status_code == 401
    assert "FAI_ONAYLANDI" in client.get("/entegrasyon").get_data(as_text=True)
