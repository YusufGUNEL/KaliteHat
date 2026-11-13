"""Uygunsuzluk kapatma (DÖF: düzeltici ve önleyici faaliyet) ve ürün kararı."""
from . import denetim, olaylar
from .muayene import acik_uygunsuzluk_sayisi
from .ortak import KuralHatasi, simdi

KARARLAR = ("YENIDEN_ISLEME", "SAPMA_KABUL", "HURDA")


def dof_kapat(conn, ncr_id, kok_neden, aksiyon, sorumlu, karar, hurda_adet=0, kapatan=None, tarih=None):
    tarih = tarih or simdi()
    ncr = conn.execute("SELECT * FROM uygunsuzluk WHERE id = ?", (ncr_id,)).fetchone()
    if ncr is None:
        raise KuralHatasi("Uygunsuzluk kaydı bulunamadı.")
    if ncr["durum"] != "ACIK":
        raise KuralHatasi("Bu kayıt zaten kapatılmış.")
    if not all((x or "").strip() for x in (kok_neden, aksiyon, sorumlu)):
        raise KuralHatasi("Kök neden, düzeltici faaliyet ve sorumlu boş bırakılamaz.")
    if karar not in KARARLAR:
        raise KuralHatasi("Karar seçilmeli: yeniden işleme, sapma ile kabul ya da hurda.")
    try:
        hurda_adet = int(hurda_adet or 0)
    except ValueError:
        raise KuralHatasi("Hurda adedi tam sayı olmalı.") from None
    ie = conn.execute("SELECT * FROM is_emri WHERE id = ?", (ncr["is_emri_id"],)).fetchone()
    if karar == "HURDA":
        if hurda_adet < 1:
            raise KuralHatasi("Hurda kararında hurda adedi en az 1 olmalı.")
        if ie["hurda_adet"] + hurda_adet > ie["adet"]:
            raise KuralHatasi(f"Toplam hurda lot adedini ({ie['adet']}) aşamaz.")
    else:
        hurda_adet = 0

    with conn:
        conn.execute(
            "UPDATE uygunsuzluk SET durum='KAPALI', kok_neden=?, aksiyon=?, sorumlu=?, karar=?, hurda_adet=?, kapanis=? "
            "WHERE id = ?",
            (kok_neden.strip(), aksiyon.strip(), sorumlu.strip(), karar, hurda_adet, tarih, ncr_id),
        )
        if hurda_adet:
            conn.execute("UPDATE is_emri SET hurda_adet = hurda_adet + ? WHERE id = ?", (hurda_adet, ie["id"]))
            olaylar.yaz(conn, "HURDA_BILDIRILDI", ie["no"],
                        {"lot": ie["lot"], "hurda_adet": hurda_adet, "toplam_hurda": ie["hurda_adet"] + hurda_adet,
                         "uygunsuzluk_no": ncr_id}, tarih)
        if acik_uygunsuzluk_sayisi(conn, ie["id"]) == 0:
            yeni = "URETIMDE" if ie["fai_onayli"] else "FAI_BEKLIYOR"
            conn.execute("UPDATE is_emri SET durum = ? WHERE id = ?", (yeni, ie["id"]))
            olaylar.yaz(conn, "LOT_KARANTINADAN_CIKTI", ie["no"], {"lot": ie["lot"], "yeni_durum": yeni}, tarih)
        denetim.kaydet(conn, kapatan or sorumlu.strip(), "DOF_KAPATILDI", "uygunsuzluk", ncr_id,
                       {"karar": karar, "hurda_adet": hurda_adet, "is_emri": ie["no"]}, tarih)
