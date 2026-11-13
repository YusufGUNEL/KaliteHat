from kalitehat.erp import dosya_oku, is_emirlerini_al


def test_csv_noktali_virgul_ve_dogrulama(conn):
    icerik = (
        "is_emri_no;parca_kodu;lot;adet;termin\n"
        "IE-2;P-100;L-2;20;2026-12-01\n"
        "IE-1;P-100;L-1;5;\n"
        "IE-3;YOK-9;L-3;5;\n"
        "IE-4;P-100;L-4;abc;\n"
        ";P-100;L-5;5;\n"
    ).encode("utf-8-sig")
    sonuc = is_emirlerini_al(conn, dosya_oku("x.csv", icerik))
    assert sonuc["eklenen"] == ["IE-2"]
    sebepler = dict(sonuc["atlanan"])
    assert sebepler["IE-1"] == "zaten kayıtlı"
    assert "kontrol planı" in sebepler["IE-3"]
    assert "sayı" in sebepler["IE-4"]
    assert "eksik" in sebepler["?"]


def test_xlsx_okuma(conn, tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["is_emri_no", "parca_kodu", "lot", "adet"])
    ws.append(["IE-9", "P-100", "L-9", 10])
    yol = tmp_path / "a.xlsx"
    wb.save(yol)
    sonuc = is_emirlerini_al(conn, dosya_oku("a.xlsx", yol.read_bytes()))
    assert sonuc["eklenen"] == ["IE-9"]
