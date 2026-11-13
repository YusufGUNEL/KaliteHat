"""Muayene kuralları: tolerans, kalibrasyon kilidi, FAI kapısı, otomatik uygunsuzluk ve lot durumu."""
from . import denetim, olaylar
from .ortak import KuralHatasi, simdi

TURLER = ("FAI", "PROSES", "FINAL")


def sinirlar(k):
    return round(k["nominal"] + k["alt_sapma"], 6), round(k["nominal"] + k["ust_sapma"], 6)


def tolerans_icinde(deger, k):
    alt, ust = sinirlar(k)
    return alt - 1e-9 <= deger <= ust + 1e-9


def tolerans_konumu(deger, k):
    """Değerin tolerans bandındaki yeri: 0 = alt sınır, 0.5 = orta, 1 = üst sınır (dışarısı <0 / >1)."""
    alt, ust = sinirlar(k)
    return (deger - alt) / (ust - alt) if ust > alt else 0.5


def kalibrasyon_gecerli(alet, gun):
    return alet["kalibrasyon_bitis"] >= gun


def is_emri_bul(conn, no):
    ie = conn.execute("SELECT * FROM is_emri WHERE no = ?", (no,)).fetchone()
    if ie is None:
        raise KuralHatasi(f"İş emri bulunamadı: {no}")
    return ie


def acik_uygunsuzluk_sayisi(conn, is_emri_id):
    return conn.execute(
        "SELECT COUNT(*) FROM uygunsuzluk WHERE is_emri_id = ? AND durum = 'ACIK'", (is_emri_id,)
    ).fetchone()[0]


def _kapiyi_kontrol_et(conn, ie, tur):
    if tur not in TURLER:
        raise KuralHatasi(f"Geçersiz muayene türü: {tur}")
    if ie["durum"] == "ONAYLI":
        raise KuralHatasi("Lot final muayeneden geçti ve ERP'ye sevke uygun bildirildi; yeni muayene açılamaz.")
    if tur == "FAI" and ie["fai_onayli"]:
        raise KuralHatasi("Bu iş emrinin ilk parça onayı zaten verilmiş.")
    if tur != "FAI" and not ie["fai_onayli"]:
        raise KuralHatasi("İlk parça muayenesi (FAI) onaylanmadan seri muayene yapılamaz.")
    if tur == "FINAL" and acik_uygunsuzluk_sayisi(conn, ie["id"]):
        raise KuralHatasi("Açık uygunsuzluk varken final muayene yapılamaz; önce DÖF kapatılmalı.")


def _olcumleri_dogrula(conn, ie, olcumler, gun):
    karakteristikler = {
        k["id"]: k for k in conn.execute("SELECT * FROM karakteristik WHERE parca_id = ?", (ie["parca_id"],))
    }
    gelen = [int(o["karakteristik_id"]) for o in olcumler]
    if sorted(gelen) != sorted(karakteristikler):
        raise KuralHatasi("Kontrol planındaki her karakteristik bir kez ölçülmeli.")

    hazir = []
    for o in olcumler:
        k = karakteristikler[int(o["karakteristik_id"])]
        try:
            deger = float(str(o["deger"]).strip().replace(",", "."))
        except ValueError:
            raise KuralHatasi(f"{k['no']}. karakteristik ({k['ad']}) için geçerli bir sayı girilmeli.") from None
        alet = conn.execute("SELECT * FROM alet WHERE id = ?", (o["alet_id"],)).fetchone()
        if alet is None:
            raise KuralHatasi(f"{k['ad']}: ölçüm aleti seçilmeli.")
        if alet["tip"] != k["alet_tipi"]:
            raise KuralHatasi(f"{k['ad']}: kontrol planı '{k['alet_tipi']}' istiyor, seçilen alet '{alet['tip']}'.")
        if not kalibrasyon_gecerli(alet, gun):
            raise KuralHatasi(
                f"{alet['kod']} ({alet['ad']}) kalibrasyonu {alet['kalibrasyon_bitis']} tarihinde bitmiş; "
                "bu aletle ölçüm kaydedilemez."
            )
        hazir.append((k, deger, alet, tolerans_icinde(deger, k)))
    return hazir


def muayene_kaydet(conn, is_emri_no, tur, personel, olcumler, tarih=None):
    """olcumler: [{"karakteristik_id", "deger", "alet_id"}]. Muayene id döner.

    Bütün kurallar yazmadan önce kontrol edilir; yazma işlemleri (muayene, ölçümler, uygunsuzluklar,
    lot durumu, ERP olayı, denetim kaydı) tek transaction'dır: ya hepsi olur ya hiçbiri.
    """
    tarih = tarih or simdi()
    if not (personel or "").strip():
        raise KuralHatasi("Muayeneyi yapan personel belli olmalı.")
    ie = is_emri_bul(conn, is_emri_no)
    _kapiyi_kontrol_et(conn, ie, tur)
    hazir = _olcumleri_dogrula(conn, ie, olcumler, tarih[:10])
    hepsi_uygun = all(h[3] for h in hazir)

    with conn:
        numune = conn.execute("SELECT COUNT(*) FROM muayene WHERE is_emri_id = ?", (ie["id"],)).fetchone()[0] + 1
        muayene_id = conn.execute(
            "INSERT INTO muayene (is_emri_id, tur, numune_no, personel, tarih, sonuc) VALUES (?,?,?,?,?,?)",
            (ie["id"], tur, numune, personel.strip(), tarih, "UYGUN" if hepsi_uygun else "RED"),
        ).lastrowid

        red_sayisi = 0
        for k, deger, alet, uygun in hazir:
            olcum_id = conn.execute(
                "INSERT INTO olcum (muayene_id, karakteristik_id, deger, alet_id, uygun) VALUES (?,?,?,?,?)",
                (muayene_id, k["id"], deger, alet["id"], int(uygun)),
            ).lastrowid
            if not uygun:
                red_sayisi += 1
                alt, ust = sinirlar(k)
                conn.execute(
                    "INSERT INTO uygunsuzluk (is_emri_id, olcum_id, aciklama, acilis) VALUES (?,?,?,?)",
                    (ie["id"], olcum_id,
                     f"{tur} – {k['no']}. {k['ad']}: ölçülen {deger:g} {k['birim']}, sınır {alt:g} / {ust:g}", tarih),
                )

        olay_verisi = {"lot": ie["lot"], "muayene_id": muayene_id, "muayene_turu": tur}
        if not hepsi_uygun:
            conn.execute("UPDATE is_emri SET durum = 'KARANTINA' WHERE id = ?", (ie["id"],))
            if ie["durum"] != "KARANTINA":
                olaylar.yaz(conn, "LOT_KARANTINAYA_ALINDI", ie["no"],
                            {**olay_verisi, "tolerans_disi_olcum": red_sayisi}, tarih)
        elif tur == "FAI":
            conn.execute("UPDATE is_emri SET fai_onayli = 1, durum = 'URETIMDE' WHERE id = ?", (ie["id"],))
            olaylar.yaz(conn, "FAI_ONAYLANDI", ie["no"], olay_verisi, tarih)
        elif tur == "FINAL":
            conn.execute("UPDATE is_emri SET durum = 'ONAYLI' WHERE id = ?", (ie["id"],))
            olaylar.yaz(conn, "LOT_SEVKE_UYGUN", ie["no"],
                        {**olay_verisi, "saglam_adet": ie["adet"] - ie["hurda_adet"], "hurda_adet": ie["hurda_adet"]},
                        tarih)

        denetim.kaydet(conn, personel.strip(), "MUAYENE_KAYDEDILDI", "is_emri", ie["no"],
                       {"muayene_id": muayene_id, "tur": tur, "sonuc": "UYGUN" if hepsi_uygun else "RED"}, tarih)
    return muayene_id
