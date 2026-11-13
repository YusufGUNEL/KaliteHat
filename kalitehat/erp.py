"""ERP'den gelen veri: iş emri içe aktarma (dosya ve API) ve ERP'nin geri okuduğu kalite özeti."""
import csv
import io

from . import denetim
from .muayene import acik_uygunsuzluk_sayisi, is_emri_bul
from .ortak import simdi

ZORUNLU_ALANLAR = ("is_emri_no", "parca_kodu", "lot", "adet")


def dosya_oku(dosya_adi, icerik):
    """CSV (; ya da ,) veya XLSX içeriğini satır sözlüklerine çevirir."""
    if dosya_adi.lower().endswith(".xlsx"):
        from openpyxl import load_workbook

        sayfa = load_workbook(io.BytesIO(icerik), read_only=True, data_only=True).active
        satirlar = list(sayfa.iter_rows(values_only=True))
        if not satirlar:
            return []
        basliklar = [str(b).strip() if b is not None else "" for b in satirlar[0]]
        return [dict(zip(basliklar, s, strict=False)) for s in satirlar[1:] if any(v is not None for v in s)]

    metin = icerik.decode("utf-8-sig")
    ilk = metin.splitlines()[0] if metin else ""
    ayirici = ";" if ilk.count(";") >= ilk.count(",") else ","
    return list(csv.DictReader(io.StringIO(metin), delimiter=ayirici))


def _satiri_dogrula(conn, satir):
    """(temiz_satir, None) ya da (None, sebep)."""
    s = {str(k).strip(): ("" if v is None else str(v).strip()) for k, v in satir.items() if k}
    eksik = [a for a in ZORUNLU_ALANLAR if not s.get(a)]
    if eksik:
        return None, "eksik alan: " + ", ".join(eksik)
    try:
        adet = int(float(s["adet"]))
    except ValueError:
        return None, f"adet sayı değil: {s['adet']}"
    if adet < 1:
        return None, "adet en az 1 olmalı"
    parca = conn.execute("SELECT id FROM parca WHERE kod = ?", (s["parca_kodu"],)).fetchone()
    if parca is None:
        return None, f"kontrol planı olmayan parça: {s['parca_kodu']}"
    return {**s, "adet": adet, "parca_id": parca["id"]}, None


def is_emirlerini_al(conn, satirlar, kaynak="ERP", kullanici="ERP"):
    """Her satırı doğrular, geçerlileri ekler. {"eklenen": [no], "atlanan": [(no, sebep)]} döner.

    Aynı iş emri ikinci kez gelirse "zaten kayıtlı" diye atlanır; ERP aynı dosyayı ya da isteği
    tekrar gönderse bile çift kayıt oluşmaz (iş emri no doğal tekillik anahtarıdır).
    """
    eklenen, atlanan = [], []
    with conn:
        for satir in satirlar:
            no = str(satir.get("is_emri_no") or "").strip() or "?"
            temiz, sebep = _satiri_dogrula(conn, satir)
            if sebep:
                atlanan.append((no, sebep))
                continue
            if conn.execute("SELECT 1 FROM is_emri WHERE no = ?", (no,)).fetchone():
                atlanan.append((no, "zaten kayıtlı"))
                continue
            conn.execute(
                "INSERT INTO is_emri (no, parca_id, lot, adet, termin, kaynak, olusturma) VALUES (?,?,?,?,?,?,?)",
                (no, temiz["parca_id"], temiz["lot"], temiz["adet"], temiz.get("termin") or None, kaynak, simdi()),
            )
            eklenen.append(no)
        if eklenen:
            denetim.kaydet(conn, kullanici, "IS_EMRI_ALINDI", "is_emri", ",".join(eklenen),
                           {"kaynak": kaynak, "adet": len(eklenen), "atlanan": len(atlanan)})
    return {"eklenen": eklenen, "atlanan": atlanan}


def kalite_ozeti(conn, no):
    """ERP'nin bir iş emri için okuduğu kalite durumu."""
    ie = is_emri_bul(conn, no)
    son = conn.execute(
        "SELECT tur, sonuc, tarih FROM muayene WHERE is_emri_id = ? ORDER BY id DESC LIMIT 1", (ie["id"],)
    ).fetchone()
    return {
        "is_emri_no": ie["no"],
        "lot": ie["lot"],
        "durum": ie["durum"],
        "sevke_uygun": ie["durum"] == "ONAYLI",
        "fai_onayli": bool(ie["fai_onayli"]),
        "adet": ie["adet"],
        "hurda_adet": ie["hurda_adet"],
        "saglam_adet": ie["adet"] - ie["hurda_adet"],
        "acik_uygunsuzluk": acik_uygunsuzluk_sayisi(conn, ie["id"]),
        "son_muayene": dict(son) if son else None,
    }
