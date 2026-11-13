"""Kalite kuralları. Web katmanı ve ERP köprüsü sadece bu fonksiyonları çağırır."""
import statistics
from datetime import date, datetime

TURLER = ("FAI", "PROSES", "FINAL")
KARARLAR = ("YENIDEN_ISLEME", "SAPMA_KABUL", "HURDA")


class KuralHatasi(Exception):
    pass


def simdi():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def sinirlar(k):
    return round(k["nominal"] + k["alt_sapma"], 6), round(k["nominal"] + k["ust_sapma"], 6)


def tolerans_icinde(deger, k):
    alt, ust = sinirlar(k)
    return alt - 1e-9 <= deger <= ust + 1e-9


def kalibrasyon_gecerli(alet, gun):
    return alet["kalibrasyon_bitis"] >= gun


def is_emri_bul(conn, no):
    ie = conn.execute("SELECT * FROM is_emri WHERE no = ?", (no,)).fetchone()
    if ie is None:
        raise KuralHatasi(f"İş emri bulunamadı: {no}")
    return ie


def muayene_kaydet(conn, is_emri_no, tur, personel, olcumler, tarih=None):
    """olcumler: [{"karakteristik_id", "deger", "alet_id"}]. Muayene id döner."""
    tarih = tarih or simdi()
    gun = tarih[:10]
    ie = is_emri_bul(conn, is_emri_no)

    if tur not in TURLER:
        raise KuralHatasi(f"Geçersiz muayene türü: {tur}")
    if not personel.strip():
        raise KuralHatasi("Muayeneyi yapan personel yazılmalı.")
    if ie["durum"] == "ONAYLI":
        raise KuralHatasi("Lot final muayeneden geçti ve ERP'ye onaylı bildirildi; yeni muayene açılamaz.")
    if tur == "FAI" and ie["fai_onayli"]:
        raise KuralHatasi("Bu iş emrinin ilk parça onayı zaten verilmiş.")
    if tur != "FAI" and not ie["fai_onayli"]:
        raise KuralHatasi("İlk parça muayenesi (FAI) onaylanmadan seri muayene yapılamaz.")
    if tur == "FINAL" and acik_uygunsuzluk_sayisi(conn, ie["id"]):
        raise KuralHatasi("Açık uygunsuzluk varken final muayene yapılamaz; önce DÖF kapatılmalı.")

    karakteristikler = {
        k["id"]: k
        for k in conn.execute("SELECT * FROM karakteristik WHERE parca_id = ?", (ie["parca_id"],))
    }
    gelen = {int(o["karakteristik_id"]) for o in olcumler}
    if gelen != set(karakteristikler) or len(olcumler) != len(karakteristikler):
        raise KuralHatasi("Kontrol planındaki her karakteristik bir kez ölçülmeli.")

    hazir = []
    for o in olcumler:
        k = karakteristikler[int(o["karakteristik_id"])]
        try:
            deger = float(str(o["deger"]).replace(",", "."))
        except (TypeError, ValueError):
            raise KuralHatasi(f"{k['no']}. karakteristik ({k['ad']}) için geçerli bir sayı girilmeli.")
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

    hepsi_uygun = all(h[3] for h in hazir)
    numune = conn.execute("SELECT COUNT(*) FROM muayene WHERE is_emri_id = ?", (ie["id"],)).fetchone()[0] + 1
    cur = conn.execute(
        "INSERT INTO muayene (is_emri_id, tur, numune_no, personel, tarih, sonuc) VALUES (?,?,?,?,?,?)",
        (ie["id"], tur, numune, personel.strip(), tarih, "UYGUN" if hepsi_uygun else "RED"),
    )
    muayene_id = cur.lastrowid

    for k, deger, alet, uygun in hazir:
        cur = conn.execute(
            "INSERT INTO olcum (muayene_id, karakteristik_id, deger, alet_id, uygun) VALUES (?,?,?,?,?)",
            (muayene_id, k["id"], deger, alet["id"], int(uygun)),
        )
        if not uygun:
            alt, ust = sinirlar(k)
            conn.execute(
                "INSERT INTO uygunsuzluk (is_emri_id, olcum_id, aciklama, acilis) VALUES (?,?,?,?)",
                (ie["id"], cur.lastrowid,
                 f"{tur} – {k['no']}. {k['ad']}: ölçülen {deger:g} {k['birim']}, sınır {alt:g} / {ust:g}",
                 tarih),
            )

    if not hepsi_uygun:
        conn.execute("UPDATE is_emri SET durum = 'KARANTINA' WHERE id = ?", (ie["id"],))
    elif tur == "FAI":
        conn.execute("UPDATE is_emri SET fai_onayli = 1, durum = 'URETIMDE' WHERE id = ?", (ie["id"],))
    elif tur == "FINAL":
        conn.execute("UPDATE is_emri SET durum = 'ONAYLI' WHERE id = ?", (ie["id"],))
    conn.commit()
    return muayene_id


def acik_uygunsuzluk_sayisi(conn, is_emri_id):
    return conn.execute(
        "SELECT COUNT(*) FROM uygunsuzluk WHERE is_emri_id = ? AND durum = 'ACIK'", (is_emri_id,)
    ).fetchone()[0]


def dof_kapat(conn, ncr_id, kok_neden, aksiyon, sorumlu, karar, hurda_adet=0, tarih=None):
    ncr = conn.execute("SELECT * FROM uygunsuzluk WHERE id = ?", (ncr_id,)).fetchone()
    if ncr is None:
        raise KuralHatasi("Uygunsuzluk kaydı bulunamadı.")
    if ncr["durum"] != "ACIK":
        raise KuralHatasi("Bu kayıt zaten kapatılmış.")
    if not (kok_neden or "").strip() or not (aksiyon or "").strip() or not (sorumlu or "").strip():
        raise KuralHatasi("Kök neden, düzeltici faaliyet ve sorumlu boş bırakılamaz.")
    if karar not in KARARLAR:
        raise KuralHatasi("Karar seçilmeli: yeniden işleme, sapma kabul ya da hurda.")
    hurda_adet = int(hurda_adet or 0)
    ie = conn.execute("SELECT * FROM is_emri WHERE id = ?", (ncr["is_emri_id"],)).fetchone()
    if karar == "HURDA":
        if hurda_adet < 1:
            raise KuralHatasi("Hurda kararında hurda adedi en az 1 olmalı.")
        if ie["hurda_adet"] + hurda_adet > ie["adet"]:
            raise KuralHatasi(f"Toplam hurda lot adedini ({ie['adet']}) aşamaz.")
    else:
        hurda_adet = 0

    conn.execute(
        "UPDATE uygunsuzluk SET durum='KAPALI', kok_neden=?, aksiyon=?, sorumlu=?, karar=?, hurda_adet=?, kapanis=? "
        "WHERE id = ?",
        (kok_neden.strip(), aksiyon.strip(), sorumlu.strip(), karar, hurda_adet, tarih or simdi(), ncr_id),
    )
    conn.execute("UPDATE is_emri SET hurda_adet = hurda_adet + ? WHERE id = ?", (hurda_adet, ie["id"]))
    if acik_uygunsuzluk_sayisi(conn, ie["id"]) == 0:
        yeni = "URETIMDE" if ie["fai_onayli"] else "FAI_BEKLIYOR"
        conn.execute("UPDATE is_emri SET durum = ? WHERE id = ?", (yeni, ie["id"]))
    conn.commit()


def yetenek(degerler, alt, ust):
    """Proses yeterliliği. n<2 ya da sapma 0 ise None."""
    if len(degerler) < 2:
        return None
    ort = statistics.mean(degerler)
    s = statistics.stdev(degerler)
    if s == 0:
        return None
    return {
        "n": len(degerler),
        "ort": ort,
        "s": s,
        "cp": (ust - alt) / (6 * s),
        "cpk": min(ust - ort, ort - alt) / (3 * s),
    }


def kalite_ozeti(conn, no):
    """ERP'nin geri okuduğu özet."""
    ie = is_emri_bul(conn, no)
    son = conn.execute(
        "SELECT tur, sonuc, tarih FROM muayene WHERE is_emri_id = ? ORDER BY id DESC LIMIT 1", (ie["id"],)
    ).fetchone()
    return {
        "is_emri_no": ie["no"],
        "lot": ie["lot"],
        "durum": ie["durum"],
        "sevke_uygun": ie["durum"] == "ONAYLI",
        "adet": ie["adet"],
        "hurda_adet": ie["hurda_adet"],
        "saglam_adet": ie["adet"] - ie["hurda_adet"],
        "acik_uygunsuzluk": acik_uygunsuzluk_sayisi(conn, ie["id"]),
        "son_muayene": dict(son) if son else None,
    }


def bugun():
    return date.today().isoformat()
