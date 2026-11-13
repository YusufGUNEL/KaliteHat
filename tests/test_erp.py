"""ERP köprüsü: dosyadan içe aktarma ve olay kuyruğu (outbox) teslimi."""
import json
from datetime import datetime

from openpyxl import Workbook

from kalitehat import olaylar
from kalitehat.erp import dosya_oku, is_emirlerini_al


def test_csv_noktali_virgul_ve_dogrulama(conn):
    icerik = (
        "is_emri_no;parca_kodu;lot;adet;termin\n"
        "IE-2;P-100;L-2;20;2026-12-01\n"
        "IE-1;P-100;L-1;5;\n"
        "IE-3;YOK-9;L-3;5;\n"
        "IE-4;P-100;L-4;abc;\n"
        "IE-5;P-100;L-5;0;\n"
        ";P-100;L-6;5;\n"
    ).encode("utf-8-sig")
    sonuc = is_emirlerini_al(conn, dosya_oku("x.csv", icerik))
    assert sonuc["eklenen"] == ["IE-2"]
    sebep = dict(sonuc["atlanan"])
    assert sebep["IE-1"] == "zaten kayıtlı"
    assert "kontrol planı" in sebep["IE-3"]
    assert "sayı" in sebep["IE-4"]
    assert "en az 1" in sebep["IE-5"]
    assert "eksik" in sebep["?"]


def test_ayni_dosya_iki_kez_yuklenince_cift_kayit_olmaz(conn):
    icerik = b"is_emri_no,parca_kodu,lot,adet\nIE-7,P-100,L-7,3\n"
    assert is_emirlerini_al(conn, dosya_oku("a.csv", icerik))["eklenen"] == ["IE-7"]
    assert is_emirlerini_al(conn, dosya_oku("a.csv", icerik))["eklenen"] == []
    assert conn.execute("SELECT COUNT(*) FROM is_emri WHERE no='IE-7'").fetchone()[0] == 1


def test_xlsx_okuma(conn, tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["is_emri_no", "parca_kodu", "lot", "adet"])
    ws.append(["IE-9", "P-100", "L-9", 10])
    yol = tmp_path / "a.xlsx"
    wb.save(yol)
    assert is_emirlerini_al(conn, dosya_oku("a.xlsx", yol.read_bytes()))["eklenen"] == ["IE-9"]


def _olay_ekle(conn, n=2):
    with conn:
        for i in range(n):
            olaylar.yaz(conn, "FAI_ONAYLANDI", f"IE-{i}", {"lot": f"L{i}"}, "2026-11-14 08:00")


def test_outbox_teslim_ve_idempotency_anahtari(conn):
    _olay_ekle(conn)
    gelen = []
    s = olaylar.gonder_bekleyenler(conn, "http://erp", lambda url, govde, anahtar, api: gelen.append((anahtar, govde)),
                                   an=datetime(2026, 11, 14, 9, 0))
    assert s == {"gonderilen": 2, "hatali": 0}
    assert [a for a, _ in gelen] == ["kalitehat-olay-1", "kalitehat-olay-2"]
    assert gelen[0][1]["veri"] == {"lot": "L0"}
    # tekrar çağrıda gönderilmiş olay yeniden gitmez
    assert olaylar.gonder_bekleyenler(conn, "http://erp", lambda *a: None,
                                      an=datetime(2026, 11, 14, 9, 5))["gonderilen"] == 0


def test_outbox_hata_geri_cekilme_ve_vazgecme(conn):
    _olay_ekle(conn, 1)

    def bozuk(*_):
        raise TimeoutError("ERP yanıt vermedi")

    an = datetime(2026, 11, 14, 9, 0)
    assert olaylar.gonder_bekleyenler(conn, "http://erp", bozuk, an=an)["hatali"] == 1
    o = conn.execute("SELECT * FROM olay").fetchone()
    assert (o["durum"], o["deneme"], o["sonraki_deneme"]) == ("HATA", 1, "2026-11-14 09:01")
    assert "yanıt vermedi" in o["son_hata"]

    # süre dolmadan tekrar denenmez
    assert olaylar.gonder_bekleyenler(conn, "http://erp", bozuk, an=an)["hatali"] == 0

    for dakika in (1, 3, 7, 15, 31):
        olaylar.gonder_bekleyenler(conn, "http://erp", bozuk, an=datetime(2026, 11, 14, 9, dakika))
    o = conn.execute("SELECT * FROM olay").fetchone()
    assert (o["durum"], o["deneme"]) == ("VAZGECILDI", olaylar.EN_FAZLA_DENEME)

    olaylar.yeniden_kuyruga_al(conn, o["id"])
    assert olaylar.gonder_bekleyenler(conn, "http://erp", lambda *a: None)["gonderilen"] == 1


def test_disa_ver_bicimi(conn):
    _olay_ekle(conn, 1)
    o = olaylar.disa_ver(conn.execute("SELECT * FROM olay").fetchone())
    assert set(o) == {"olay_id", "anahtar", "tur", "is_emri_no", "zaman", "veri"}
    json.dumps(o)
