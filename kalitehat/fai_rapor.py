"""İlk parça muayene (FAI) raporu: AS9102 Form 3 (karakteristik doğrulama) düzenine benzer Excel çıktısı."""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .muayene import sinirlar
from .ortak import KuralHatasi

INCE = Side(style="thin", color="999999")
CERCEVE = Border(left=INCE, right=INCE, top=INCE, bottom=INCE)
BASLIK_DOLGU = PatternFill("solid", fgColor="E8EBE6")
RED_DOLGU = PatternFill("solid", fgColor="F8D7D3")


def _yaz(ws, satir, sutun, deger):
    """Hücreye yazar; '=' ile başlayan metin formül olarak değil düz metin olarak kalır (ERP'den gelen veri)."""
    c = ws.cell(satir, sutun, deger)
    if isinstance(deger, str) and deger.startswith("="):
        c.data_type = "s"
    return c


def olustur(conn, is_emri_no):
    ie = conn.execute(
        "SELECT ie.*, p.kod parca_kod, p.ad parca_ad, p.revizyon, p.malzeme FROM is_emri ie "
        "JOIN parca p ON p.id = ie.parca_id WHERE ie.no = ?", (is_emri_no,)
    ).fetchone()
    if ie is None:
        raise KuralHatasi(f"İş emri bulunamadı: {is_emri_no}")
    fai = conn.execute(
        "SELECT * FROM muayene WHERE is_emri_id = ? AND tur = 'FAI' ORDER BY id DESC LIMIT 1", (ie["id"],)
    ).fetchone()
    if fai is None:
        raise KuralHatasi("Bu iş emrinde ilk parça muayenesi yok.")
    satirlar = conn.execute(
        "SELECT k.*, o.deger, o.uygun, a.kod alet_kod, a.ad alet_ad, a.kalibrasyon_bitis FROM olcum o "
        "JOIN karakteristik k ON k.id = o.karakteristik_id JOIN alet a ON a.id = o.alet_id "
        "WHERE o.muayene_id = ? ORDER BY k.no", (fai["id"],)
    ).fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "FAI Form 3"
    ws["A1"] = "İLK PARÇA MUAYENE RAPORU (FAI) — Karakteristik doğrulama"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "AS9102 Form 3 düzenine benzer biçimde hazırlanmıştır."
    ws["A2"].font = Font(italic=True, color="666666")

    bilgiler = [
        ("Parça no", ie["parca_kod"]), ("Parça adı", ie["parca_ad"]), ("Revizyon", ie["revizyon"]),
        ("Malzeme", ie["malzeme"]), ("İş emri", ie["no"]), ("Lot", ie["lot"]),
        ("Muayene tarihi", fai["tarih"]), ("Muayene eden", fai["personel"]),
        ("Sonuç", "KABUL" if fai["sonuc"] == "UYGUN" else "RED"),
    ]
    for i, (etiket, deger) in enumerate(bilgiler, start=4):
        ws.cell(i, 1, etiket).font = Font(bold=True)
        _yaz(ws, i, 2, deger)

    basliklar = ["Kar. no", "Karakteristik", "Nominal", "Alt sapma", "Üst sapma", "Alt sınır", "Üst sınır",
                 "Birim", "Ölçülen", "Sonuç", "Ölçüm aleti", "Alet kal. bitişi", "Kritik"]
    bas = len(bilgiler) + 5
    for j, b in enumerate(basliklar, start=1):
        c = ws.cell(bas, j, b)
        c.font, c.fill, c.border = Font(bold=True), BASLIK_DOLGU, CERCEVE
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, r in enumerate(satirlar, start=bas + 1):
        alt, ust = sinirlar(r)
        degerler = [r["no"], r["ad"], r["nominal"], r["alt_sapma"], r["ust_sapma"], alt, ust, r["birim"],
                    r["deger"], "UYGUN" if r["uygun"] else "RED", f"{r['alet_kod']} {r['alet_ad']}",
                    r["kalibrasyon_bitis"], "Evet" if r["kritik"] else ""]
        for j, d in enumerate(degerler, start=1):
            c = _yaz(ws, i, j, d)
            c.border = CERCEVE
            if not r["uygun"]:
                c.fill = RED_DOLGU
            if j in (3, 4, 5, 6, 7, 9):
                c.number_format = "0.000"
    for kolon, genislik in zip("ABCDEFGHIJKLM", (8, 28, 10, 10, 10, 10, 10, 7, 10, 9, 30, 14, 8), strict=True):
        ws.column_dimensions[kolon].width = genislik
    ws.freeze_panes = ws.cell(bas + 1, 1)

    imza = bas + len(satirlar) + 3
    for j, etiket in enumerate(["Hazırlayan", "Kalite onayı", "Tarih"]):
        ws.cell(imza, 1 + j * 4, etiket).font = Font(bold=True)
        ws.cell(imza + 2, 1 + j * 4, "____________________")

    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue(), f"FAI_{ie['parca_kod']}_{ie['no']}.xlsx"
