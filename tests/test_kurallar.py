"""Muayene ve DÖF kuralları: kalite sisteminin çekirdeği."""
import json

import pytest
from conftest import olc

from kalitehat.dof import dof_kapat
from kalitehat.erp import kalite_ozeti
from kalitehat.muayene import muayene_kaydet, tolerans_icinde, tolerans_konumu
from kalitehat.ortak import KuralHatasi


def durum(conn):
    return tuple(conn.execute("SELECT durum, fai_onayli, hurda_adet FROM is_emri WHERE no='IE-1'").fetchone())


def olay_turleri(conn):
    return [r[0] for r in conn.execute("SELECT tur FROM olay ORDER BY id")]


def test_tolerans_sinirlari_dahil():
    k = {"nominal": 12.0, "alt_sapma": 0.0, "ust_sapma": 0.018}
    assert tolerans_icinde(12.0, k) and tolerans_icinde(12.018, k)
    assert not tolerans_icinde(12.019, k) and not tolerans_icinde(11.999, k)
    assert tolerans_konumu(12.009, k) == pytest.approx(0.5)


def test_fai_olmadan_seri_muayene_yok(conn):
    with pytest.raises(KuralHatasi, match="FAI"):
        muayene_kaydet(conn, "IE-1", "PROSES", "Ali", olc(12.01, 40.0))


def test_fai_uygun_ise_uretime_gecer_ve_erp_olayi_yazilir(conn):
    muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0))
    assert durum(conn) == ("URETIMDE", 1, 0)
    assert olay_turleri(conn) == ["FAI_ONAYLANDI"]
    with pytest.raises(KuralHatasi, match="zaten"):
        muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0))


def test_kalibrasyonu_gecmis_alet_reddedilir_ve_hicbir_sey_yazilmaz(conn):
    with pytest.raises(KuralHatasi, match="kalibrasyon"):
        muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0, cap_alet=3))
    for tablo in ("muayene", "olcum", "olay", "denetim"):
        assert conn.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0] == 0, tablo


def test_yanlis_alet_tipi_reddedilir(conn):
    with pytest.raises(KuralHatasi, match="Mikrometre"):
        muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0, cap_alet=2))


def test_eksik_ya_da_tekrarli_karakteristik_reddedilir(conn):
    with pytest.raises(KuralHatasi, match="her karakteristik"):
        muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0)[:1])
    cift = [olc(12.01, 40.0)[0]] * 2
    with pytest.raises(KuralHatasi, match="her karakteristik"):
        muayene_kaydet(conn, "IE-1", "FAI", "Ali", cift)


def test_sayi_olmayan_deger_ve_virgul(conn):
    with pytest.raises(KuralHatasi, match="geçerli bir sayı"):
        muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc("abc", 40.0))
    muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc("12,005", "40"))
    assert conn.execute("SELECT deger FROM olcum WHERE karakteristik_id=1").fetchone()[0] == 12.005


def test_tolerans_disi_karantina_dof_ve_sevk(conn):
    muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0))
    muayene_kaydet(conn, "IE-1", "PROSES", "Ali", olc(12.03, 40.0))
    assert durum(conn)[0] == "KARANTINA"
    ncr = conn.execute("SELECT * FROM uygunsuzluk").fetchall()
    assert len(ncr) == 1 and "Çap" in ncr[0]["aciklama"]

    # karantinadayken ikinci red, ikinci karantina olayı üretmez
    muayene_kaydet(conn, "IE-1", "PROSES", "Ali", olc(12.04, 40.0))
    assert olay_turleri(conn).count("LOT_KARANTINAYA_ALINDI") == 1

    with pytest.raises(KuralHatasi, match="final"):
        muayene_kaydet(conn, "IE-1", "FINAL", "Ali", olc(12.01, 40.0))
    with pytest.raises(KuralHatasi, match="boş"):
        dof_kapat(conn, ncr[0]["id"], "", "x", "y", "HURDA", 2)

    dof_kapat(conn, ncr[0]["id"], "Takım aşınması", "Takım ömrü 300 parçaya indirildi", "Veli", "HURDA", 2)
    assert durum(conn)[0] == "KARANTINA"  # ikinci NCR hâlâ açık
    ikinci = conn.execute("SELECT id FROM uygunsuzluk WHERE durum='ACIK'").fetchone()["id"]
    dof_kapat(conn, ikinci, "Aynı neden", "Aynı aksiyon", "Veli", "YENIDEN_ISLEME")
    assert durum(conn) == ("URETIMDE", 1, 2)

    muayene_kaydet(conn, "IE-1", "FINAL", "Ali", olc(12.01, 40.0))
    oz = kalite_ozeti(conn, "IE-1")
    assert oz["sevke_uygun"] and oz["saglam_adet"] == 48 and oz["acik_uygunsuzluk"] == 0
    assert olay_turleri(conn) == ["FAI_ONAYLANDI", "LOT_KARANTINAYA_ALINDI", "HURDA_BILDIRILDI",
                                  "LOT_KARANTINADAN_CIKTI", "LOT_SEVKE_UYGUN"]
    sevk = json.loads(conn.execute("SELECT veri FROM olay WHERE tur='LOT_SEVKE_UYGUN'").fetchone()[0])
    assert sevk["saglam_adet"] == 48

    with pytest.raises(KuralHatasi, match="sevke uygun"):
        muayene_kaydet(conn, "IE-1", "PROSES", "Ali", olc(12.01, 40.0))


def test_fai_red_sonrasi_tekrar_fai_bekler(conn):
    muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.05, 40.0))
    ncr = conn.execute("SELECT id FROM uygunsuzluk").fetchone()
    dof_kapat(conn, ncr["id"], "Ofset hatası", "Ofset düzeltildi", "Veli", "YENIDEN_ISLEME")
    assert durum(conn) == ("FAI_BEKLIYOR", 0, 0)


def test_hurda_lot_adedini_asamaz_ve_kapali_kayit_tekrar_kapanmaz(conn):
    muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.05, 40.0))
    ncr = conn.execute("SELECT id FROM uygunsuzluk").fetchone()["id"]
    with pytest.raises(KuralHatasi, match="aşamaz"):
        dof_kapat(conn, ncr, "a", "b", "c", "HURDA", 51)
    with pytest.raises(KuralHatasi, match="en az 1"):
        dof_kapat(conn, ncr, "a", "b", "c", "HURDA", 0)
    dof_kapat(conn, ncr, "a", "b", "c", "SAPMA_KABUL", 5)  # hurda dışı kararda adet yok sayılır
    assert durum(conn)[2] == 0
    with pytest.raises(KuralHatasi, match="zaten"):
        dof_kapat(conn, ncr, "a", "b", "c", "SAPMA_KABUL")


def test_denetim_izi_kim_ne_yapti(conn):
    muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.05, 40.0))
    ncr = conn.execute("SELECT id FROM uygunsuzluk").fetchone()["id"]
    dof_kapat(conn, ncr, "a", "b", "Sorumlu", "YENIDEN_ISLEME", kapatan="Kalite Kişisi")
    kayit = [(r["kullanici"], r["eylem"]) for r in conn.execute("SELECT * FROM denetim ORDER BY id")]
    assert kayit == [("Ali", "MUAYENE_KAYDEDILDI"), ("Kalite Kişisi", "DOF_KAPATILDI")]
