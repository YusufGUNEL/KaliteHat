import pytest

from conftest import olc
from kalitehat.kurallar import KuralHatasi, dof_kapat, kalite_ozeti, muayene_kaydet, tolerans_icinde, yetenek


def durum(conn):
    return conn.execute("SELECT durum, fai_onayli, hurda_adet FROM is_emri WHERE no='IE-1'").fetchone()


def test_tolerans_sinirlari_dahil():
    k = {"nominal": 12.0, "alt_sapma": 0.0, "ust_sapma": 0.018}
    assert tolerans_icinde(12.0, k)
    assert tolerans_icinde(12.018, k)
    assert not tolerans_icinde(12.019, k)
    assert not tolerans_icinde(11.999, k)


def test_fai_olmadan_seri_muayene_yok(conn):
    with pytest.raises(KuralHatasi, match="FAI"):
        muayene_kaydet(conn, "IE-1", "PROSES", "Ali", olc(12.01, 40.0))


def test_fai_uygun_ise_uretime_gecer(conn):
    muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0))
    assert tuple(durum(conn)) == ("URETIMDE", 1, 0)
    with pytest.raises(KuralHatasi, match="zaten"):
        muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0))


def test_kalibrasyonu_gecmis_alet_reddedilir(conn):
    with pytest.raises(KuralHatasi, match="kalibrasyon"):
        muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0, cap_alet=3))
    assert conn.execute("SELECT COUNT(*) FROM muayene").fetchone()[0] == 0


def test_yanlis_alet_tipi_reddedilir(conn):
    with pytest.raises(KuralHatasi, match="Mikrometre"):
        muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0, cap_alet=2))


def test_eksik_karakteristik_reddedilir(conn):
    with pytest.raises(KuralHatasi, match="her karakteristik"):
        muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0)[:1])


def test_tolerans_disi_karantina_ve_dof(conn):
    muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.01, 40.0))
    muayene_kaydet(conn, "IE-1", "PROSES", "Ali", olc(12.03, 40.0))
    assert durum(conn)["durum"] == "KARANTINA"
    ncr = conn.execute("SELECT * FROM uygunsuzluk").fetchall()
    assert len(ncr) == 1 and "Çap" in ncr[0]["aciklama"]

    with pytest.raises(KuralHatasi, match="final"):
        muayene_kaydet(conn, "IE-1", "FINAL", "Ali", olc(12.01, 40.0))

    with pytest.raises(KuralHatasi, match="boş"):
        dof_kapat(conn, ncr[0]["id"], "", "x", "y", "HURDA", 2)

    dof_kapat(conn, ncr[0]["id"], "Takım aşınması", "Takım ömrü 300 parçaya indirildi", "Veli", "HURDA", 2)
    assert tuple(durum(conn)) == ("URETIMDE", 1, 2)

    muayene_kaydet(conn, "IE-1", "FINAL", "Ali", olc(12.01, 40.0))
    oz = kalite_ozeti(conn, "IE-1")
    assert oz["sevke_uygun"] and oz["saglam_adet"] == 48 and oz["acik_uygunsuzluk"] == 0

    with pytest.raises(KuralHatasi, match="onaylı"):
        muayene_kaydet(conn, "IE-1", "PROSES", "Ali", olc(12.01, 40.0))


def test_fai_red_sonrasi_tekrar_fai_bekler(conn):
    muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.05, 40.0))
    ncr = conn.execute("SELECT id FROM uygunsuzluk").fetchone()
    dof_kapat(conn, ncr["id"], "Ofset hatası", "Ofset düzeltildi", "Veli", "YENIDEN_ISLEME")
    assert tuple(durum(conn)) == ("FAI_BEKLIYOR", 0, 0)


def test_hurda_lot_adedini_asamaz(conn):
    muayene_kaydet(conn, "IE-1", "FAI", "Ali", olc(12.05, 40.0))
    ncr = conn.execute("SELECT id FROM uygunsuzluk").fetchone()
    with pytest.raises(KuralHatasi, match="aşamaz"):
        dof_kapat(conn, ncr["id"], "a", "b", "c", "HURDA", 51)


def test_yetenek_hesabi():
    y = yetenek([10.0, 10.2, 9.8, 10.1, 9.9], 9.0, 11.0)
    assert y["n"] == 5
    assert round(y["s"], 4) == 0.1581
    assert round(y["cp"], 3) == 2.108
    assert round(y["cpk"], 3) == 2.108
    assert yetenek([10.0], 9, 11) is None
    assert yetenek([10.0, 10.0], 9, 11) is None
