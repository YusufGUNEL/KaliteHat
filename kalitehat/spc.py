"""İstatistiksel proses kontrol: I-MR kontrol grafiği, proses yeterliliği ve erken uyarı kuralları.

Tekil ölçümler (alt grup = 1) için I-MR grafiği kullanılır. Proses içi sapma, ardışık ölçümlerin
farkından (hareketli aralık, MR) tahmin edilir: σ_iç = MR̄ / d2, d2 = 1,128 (n = 2 için).
  Cp, Cpk  → σ_iç ile: prosesin kısa vadede yapabileceği
  Pp, Ppk  → tüm verinin standart sapmasıyla: gerçekte olan (kayma ve aşınma dahil)
Cpk ile Ppk arasındaki büyük fark, prosesin zamanla kaydığını (ör. takım aşınması) gösterir.
"""
import statistics

D2 = 1.128      # n=2 için d2 sabiti
D4 = 3.267      # n=2 için MR grafiği üst sınır katsayısı
REFERANS_N = 20  # kontrol sınırları ilk 20 ölçümden (referans dönem) hesaplanır


def _mr_ort(degerler):
    mr = [abs(b - a) for a, b in zip(degerler, degerler[1:], strict=False)]
    return mr, (statistics.mean(mr) if mr else 0.0)


def imr(degerler, referans_n=REFERANS_N):
    """I-MR grafiği sınırları. n < 2 ya da hiç değişim yoksa None.

    Sınırlar referans dönemden (ilk `referans_n` ölçüm) hesaplanır ve sonra sabit kalır; sonraki
    ölçümler bu sınırlara göre izlenir. Sınırlar tüm veriden hesaplansaydı, yavaş bir kayma
    ortalamayı da sürükler ve kendini gizlerdi.
    """
    if len(degerler) < 2:
        return None
    referans = degerler[:referans_n] if len(degerler) > referans_n else degerler
    _, mr_ort = _mr_ort(referans)
    if mr_ort == 0:
        return None
    ort = statistics.mean(referans)
    sigma = mr_ort / D2
    mr, _ = _mr_ort(degerler)
    return {"ort": ort, "sigma_ic": sigma, "ucl": ort + 3 * sigma, "lcl": ort - 3 * sigma,
            "mr": mr, "mr_ort": mr_ort, "mr_ucl": D4 * mr_ort, "referans_n": len(referans)}


def yeterlilik(degerler, alt, ust):
    """Cp/Cpk (σ_iç) ve Pp/Ppk (σ_toplam), tüm veri üzerinden. Yetersiz veride None."""
    if len(degerler) < 2:
        return None
    _, mr_ort = _mr_ort(degerler)
    if mr_ort == 0:
        return None
    ort, s_ic = statistics.mean(degerler), mr_ort / D2
    s_top = statistics.stdev(degerler)
    sonuc = {"n": len(degerler), "ort": ort, "sigma_ic": s_ic, "sigma_toplam": s_top,
             "cp": (ust - alt) / (6 * s_ic), "cpk": min(ust - ort, ort - alt) / (3 * s_ic)}
    if s_top > 0:
        sonuc["pp"] = (ust - alt) / (6 * s_top)
        sonuc["ppk"] = min(ust - ort, ort - alt) / (3 * s_top)
    else:
        sonuc["pp"] = sonuc["ppk"] = None
    return sonuc


KURAL_ACIKLAMA = {
    1: "Kontrol sınırı dışında nokta (±3σ): özel bir neden var",
    2: "9 nokta üst üste ortalamanın aynı tarafında: proses kaymış",
    3: "6 nokta üst üste sürekli artıyor ya da azalıyor: trend (ör. takım aşınması)",
}


def kural_ihlalleri(degerler, sinir=None):
    """Western Electric / Nelson kuralları 1-3. [{"kural", "indeks", "aciklama"}] döner.

    İndeks, ihlali tamamlayan noktanın sırasıdır. Bu kurallar, ölçüm henüz tolerans içindeyken
    prosesin bozulmaya başladığını yakalar.
    """
    sinir = sinir or imr(degerler)
    if sinir is None:
        return []
    ort, ucl, lcl = sinir["ort"], sinir["ucl"], sinir["lcl"]
    ihlaller = []
    taraf_seri, onceki_taraf = 0, 0
    yon_seri, onceki_yon = 0, 0
    for i, x in enumerate(degerler):
        if x > ucl or x < lcl:
            ihlaller.append({"kural": 1, "indeks": i, "aciklama": KURAL_ACIKLAMA[1]})

        taraf = 1 if x > ort else (-1 if x < ort else 0)
        taraf_seri = taraf_seri + 1 if taraf != 0 and taraf == onceki_taraf else (1 if taraf else 0)
        onceki_taraf = taraf
        if taraf_seri == 9:
            ihlaller.append({"kural": 2, "indeks": i, "aciklama": KURAL_ACIKLAMA[2]})

        if i > 0:
            yon = 1 if x > degerler[i - 1] else (-1 if x < degerler[i - 1] else 0)
            yon_seri = yon_seri + 1 if yon != 0 and yon == onceki_yon else (1 if yon else 0)
            onceki_yon = yon
            if yon_seri == 5:  # 5 ardışık artış = 6 nokta
                ihlaller.append({"kural": 3, "indeks": i, "aciklama": KURAL_ACIKLAMA[3]})
    return ihlaller
