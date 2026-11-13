"""SPC hesapları: elle doğrulanmış küçük örneklerle."""
import pytest

from kalitehat.spc import imr, kural_ihlalleri, yeterlilik


def test_imr_sinirlari():
    s = imr([10.0, 10.2, 9.8, 10.1, 9.9])
    # MR = 0.2, 0.4, 0.3, 0.2 → MR̄ = 0.275 ; σ = 0.275 / 1.128
    assert s["mr_ort"] == pytest.approx(0.275)
    assert s["sigma_ic"] == pytest.approx(0.275 / 1.128)
    assert s["ucl"] == pytest.approx(10.0 + 3 * 0.275 / 1.128)
    assert s["mr_ucl"] == pytest.approx(3.267 * 0.275)
    assert imr([1.0]) is None and imr([1.0, 1.0]) is None


def test_sinirlar_referans_donemden():
    veri = [10.0, 10.1] * 10 + [12.0, 12.0]
    s = imr(veri, referans_n=20)
    assert s["ort"] == pytest.approx(10.05) and s["referans_n"] == 20


def test_yeterlilik():
    y = yeterlilik([10.0, 10.2, 9.8, 10.1, 9.9], 9.0, 11.0)
    sigma = 0.275 / 1.128
    assert y["cp"] == pytest.approx(2.0 / (6 * sigma))
    assert y["cpk"] == pytest.approx(1.0 / (3 * sigma))
    assert y["pp"] == pytest.approx(2.0 / (6 * 0.158114), rel=1e-4)
    assert yeterlilik([10.0], 9, 11) is None


def test_kayan_proseste_cpk_ppkdan_buyuk():
    # her ölçüm bir öncekinden biraz büyük: kısa dönem yayılım küçük, uzun dönem büyük
    veri = [10 + 0.01 * i + (0.003 if i % 2 else -0.003) for i in range(40)]
    y = yeterlilik(veri, 9.5, 11.0)
    assert y["cpk"] > y["ppk"]


def test_kural_1_sinir_disi():
    veri = [10.0, 10.1, 9.9, 10.0, 10.1, 9.9, 10.0, 10.1, 9.9, 10.0, 11.5]
    assert [i["kural"] for i in kural_ihlalleri(veri, imr(veri[:10]))] == [1]


def test_kural_2_dokuz_nokta_ayni_taraf():
    temel = [10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 9.9]
    veri = temel + [10.05, 10.1, 10.03, 10.08, 10.02, 10.06, 10.04, 10.09, 10.07]
    ihlal = [i for i in kural_ihlalleri(veri, imr(temel)) if i["kural"] == 2]
    assert [i["indeks"] for i in ihlal] == [len(veri) - 1]


def test_kural_3_trend():
    veri = [10.0, 9.9, 10.1, 10.0, 9.9, 10.0, 10.01, 10.02, 10.03, 10.04, 10.05]
    ihlal = [i for i in kural_ihlalleri(veri) if i["kural"] == 3]
    assert [i["indeks"] for i in ihlal] == [9]  # 9.9 → 10.0 → 10.01 → … → 10.04: 6 artan nokta


def test_esitlik_trendi_bozar():
    veri = [1, 2, 3, 3, 4, 5, 6, 7]
    assert not [i for i in kural_ihlalleri(veri) if i["kural"] == 3]
