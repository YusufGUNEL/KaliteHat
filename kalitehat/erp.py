"""ERP köprüsü: iş emirlerini dosyadan ya da API'den alır."""
import csv
import io

from .kurallar import simdi

ALANLAR = ("is_emri_no", "parca_kodu", "lot", "adet")


def dosya_oku(dosya_adi, icerik):
    """CSV (; ya da ,) veya XLSX içeriğini satır sözlüklerine çevirir."""
    if dosya_adi.lower().endswith(".xlsx"):
        from openpyxl import load_workbook

        ws = load_workbook(io.BytesIO(icerik), read_only=True, data_only=True).active
        satirlar = list(ws.iter_rows(values_only=True))
        if not satirlar:
            return []
        basliklar = [str(b).strip() if b is not None else "" for b in satirlar[0]]
        return [dict(zip(basliklar, s)) for s in satirlar[1:] if any(v is not None for v in s)]

    metin = icerik.decode("utf-8-sig")
    ayirici = ";" if metin.splitlines()[0].count(";") >= metin.splitlines()[0].count(",") else ","
    return list(csv.DictReader(io.StringIO(metin), delimiter=ayirici))


def is_emirlerini_al(conn, satirlar, kaynak="ERP"):
    """Her satırı doğrular, geçerlileri ekler. {"eklenen": [no], "atlanan": [(no, sebep)]} döner."""
    eklenen, atlanan = [], []
    for satir in satirlar:
        s = {k.strip(): ("" if v is None else str(v).strip()) for k, v in satir.items() if k}
        no = s.get("is_emri_no", "") or "?"
        eksik = [a for a in ALANLAR if not s.get(a)]
        if eksik:
            atlanan.append((no, "eksik alan: " + ", ".join(eksik)))
            continue
        try:
            adet = int(float(s["adet"]))
        except ValueError:
            atlanan.append((no, f"adet sayı değil: {s['adet']}"))
            continue
        if adet < 1:
            atlanan.append((no, "adet en az 1 olmalı"))
            continue
        parca = conn.execute("SELECT id FROM parca WHERE kod = ?", (s["parca_kodu"],)).fetchone()
        if parca is None:
            atlanan.append((no, f"kontrol planı olmayan parça: {s['parca_kodu']}"))
            continue
        if conn.execute("SELECT 1 FROM is_emri WHERE no = ?", (no,)).fetchone():
            atlanan.append((no, "zaten kayıtlı"))
            continue
        conn.execute(
            "INSERT INTO is_emri (no, parca_id, lot, adet, termin, kaynak, olusturma) VALUES (?,?,?,?,?,?,?)",
            (no, parca["id"], s["lot"], adet, s.get("termin") or None, kaynak, simdi()),
        )
        eklenen.append(no)
    conn.commit()
    return {"eklenen": eklenen, "atlanan": atlanan}
