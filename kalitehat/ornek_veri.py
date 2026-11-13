"""Demo veritabanı: 4 parça, 10 ölçüm aleti, 4 kullanıcı ve ~45 günlük gerçekçi üretim/muayene geçmişi.

Veride iki bilinçli hikâye var (sunumda anlatılacak):
  * SN-50 merkezleme çapı: taşlama ofseti alt toleransa kaymış (Cp iyi, Cpk kötü).
  * MB-125 pim deliği: rayba aşınıyor, ölçü lot lot büyüyor; SPC kuralları tolerans dışına
    çıkmadan önce uyarıyor, son lot karantinada.
Kullanım:  flask --app kalitehat ornek-veri   ya da   python -m kalitehat.ornek_veri
"""
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from . import kullanicilar
from .db import baglan
from .dof import dof_kapat
from .erp import is_emirlerini_al
from .muayene import muayene_kaydet

# kod, ad, rev, malzeme, [(ad, nominal, alt, üst, birim, alet tipi, kritik, adım)]
PARCALAR = [
    ("MB-125", "Hassas mengene gövdesi 125", "C", "1.2312 ıslah çeliği", [
        ("Toplam boy", 250.0, -0.1, 0.1, "mm", "Kumpas", 0, 0.01),
        ("Kızak genişliği", 125.0, -0.02, 0.0, "mm", "Mikrometre", 1, 0.001),
        ("Taban düzlemselliği", 0.0, 0.0, 0.01, "mm", "Komparatör", 1, 0.001),
        ("Pim deliği Ø12 H7", 12.0, 0.0, 0.018, "mm", "İç çap komparatörü", 1, 0.001),
    ]),
    ("SN-50", "Sıfır noktası bağlama modülü", "B", "1.2842 takım çeliği", [
        ("Merkezleme çapı Ø50 g6", 50.0, -0.025, -0.009, "mm", "Mikrometre", 1, 0.001),
        ("Yükseklik", 40.0, -0.01, 0.01, "mm", "Yükseklik mihengiri", 1, 0.001),
        ("Yüzey sertliği", 60.0, -2.0, 2.0, "HRC", "Sertlik ölçer", 0, 0.5),
    ]),
    ("FP-400", "Modüler fikstür plakası 400", "A", "7075 alüminyum", [
        ("Kalınlık", 40.0, -0.02, 0.02, "mm", "Mikrometre", 1, 0.001),
        ("Pim deliği Ø12 H7", 12.0, 0.0, 0.018, "mm", "İç çap komparatörü", 1, 0.001),
        ("Düzlemsellik", 0.0, 0.0, 0.015, "mm", "Komparatör", 1, 0.001),
        ("Toplam en", 400.0, -0.2, 0.2, "mm", "Kumpas", 0, 0.01),
    ]),
    ("PM-12", "Konumlama pimi Ø12", "A", "1.3505 rulman çeliği", [
        ("Çap Ø12 m6", 12.0, 0.007, 0.018, "mm", "Mikrometre", 1, 0.001),
        ("Boy", 30.0, -0.1, 0.1, "mm", "Kumpas", 0, 0.01),
    ]),
]

BUGUN = date.today()
ALETLER = [
    ("MK-01", "Dijital mikrometre 0-25 mm", "Mikrometre", 140),
    ("MK-02", "Dijital mikrometre 25-50 mm", "Mikrometre", 95),
    ("MK-03", "Mikrometre 100-125 mm", "Mikrometre", 200),
    ("MK-04", "Mikrometre 25-50 mm (yedek)", "Mikrometre", -13),
    ("KP-01", "Dijital kumpas 300 mm", "Kumpas", 160),
    ("KP-02", "Dijital kumpas 150 mm", "Kumpas", 21),
    ("IC-01", "İç çap komparatörü 10-18 mm", "İç çap komparatörü", 120),
    ("KM-01", "Komparatör saati 0,001", "Komparatör", 75),
    ("YM-01", "Dijital yükseklik mihengiri 300 mm", "Yükseklik mihengiri", 180),
    ("SR-01", "Rockwell sertlik ölçer", "Sertlik ölçer", 230),
]

PERSONEL = ["Mehmet Kaya", "Ayşe Demir", "Emre Şahin"]
# kullanıcı adı, ad, rol — demo parolası hepsi için "demo"
KULLANICILAR = [
    ("mehmet", "Mehmet Kaya", "OPERATOR"),
    ("ayse", "Ayşe Demir", "OPERATOR"),
    ("emre", "Emre Şahin", "OPERATOR"),
    ("zeynep", "Zeynep Arslan", "KALITE"),
    ("selin", "Selin Aydın", "YONETICI"),
]

# (karakteristik adı -> olası (kök neden, aksiyon, karar))
KOK_NEDEN = {
    "Pim deliği Ø12 H7": [("Delik büyütücü (rayba) aşınması", "Rayba ömrü 400 delikten 250 deliğe indirildi, takım ömrü sayacı eklendi", "HURDA")],
    "Merkezleme çapı Ø50 g6": [
        ("Taşlama tezgâhında ofset kayması, proses alt toleransa yakın çalışıyor", "Ofset nominal ortasına çekildi, her 20 parçada bir ölçüm", "YENIDEN_ISLEME"),
        ("Isıl işlem sonrası çarpılma", "Isıl işlem sonrası gerilim giderme adımı eklendi", "HURDA"),
    ],
    "Kızak genişliği": [("Bağlama sırasında parçanın esnemesi", "Bağlama torku talimata yazıldı (40 Nm)", "SAPMA_KABUL")],
    "Düzlemsellik": [("Alüminyumda bağlama gerilimi", "Son pasoda bağlama gevşetilip yeniden sıkılıyor", "YENIDEN_ISLEME")],
    "Kalınlık": [("Hammadde kalınlık sapması", "Tedarikçiye giriş kontrolü bildirimi yapıldı", "YENIDEN_ISLEME")],
}
VARSAYILAN_NEDEN = [("Operatör ölçüm hatası şüphesi; tekrar ölçümde de tolerans dışı", "Operatöre ölçüm eğitimi tekrarlandı", "YENIDEN_ISLEME")]


def degeri_uret(rnd, k, lot_sira, adim_no, ad):
    alt, ust = k["nominal"] + k["alt_sapma"], k["nominal"] + k["ust_sapma"]
    orta, gen = (alt + ust) / 2, ust - alt
    sigma = gen / 10                                     # Cpk ≈ 1,67: sağlıklı proses
    if ad == "Merkezleme çapı Ø50 g6":                    # ofset alta kaymış: Cpk < 1
        orta, sigma = alt + gen * 0.2, gen / 6
    elif ad == "Pim deliği Ø12 H7" and k["parca_kod"] == "MB-125":   # takım aşınması: lot lot büyüyor
        orta, sigma = alt + gen * (0.28 + 0.06 * lot_sira + 0.025 * adim_no), gen / 12
    elif ad == "Düzlemsellik":                            # alüminyum plakada bağlama gerilimi
        orta, sigma = gen * 0.55, gen / 7
    elif ad == "Taban düzlemselliği":
        orta, sigma = gen * 0.45, gen / 10
    deger = rnd.gauss(orta, sigma)
    if ad in ("Taban düzlemselliği", "Düzlemsellik"):
        deger = abs(deger)
    return deger


ACIK_NCR = "SELECT COUNT(*) FROM uygunsuzluk WHERE durum='ACIK'"


def kur(db_yolu):
    rnd = random.Random(7)
    yol = Path(db_yolu)
    yol.parent.mkdir(parents=True, exist_ok=True)
    if yol.exists():
        yol.unlink()
    conn = baglan(str(yol))
    for kadi, ad, rol in KULLANICILAR:
        kullanicilar.ekle(conn, kadi, ad, rol, "demo")

    for kod, ad, rev, malz, ks in PARCALAR:
        pid = conn.execute("INSERT INTO parca (kod, ad, revizyon, malzeme) VALUES (?,?,?,?)", (kod, ad, rev, malz)).lastrowid
        for i, (kad, nom, a, u, birim, tip, kritik, _) in enumerate(ks, 1):
            conn.execute(
                "INSERT INTO karakteristik (parca_id, no, ad, nominal, alt_sapma, ust_sapma, birim, alet_tipi, kritik)"
                " VALUES (?,?,?,?,?,?,?,?,?)", (pid, i, kad, nom, a, u, birim, tip, kritik))
    for kod, ad, tip, gun in ALETLER:
        conn.execute("INSERT INTO alet (kod, ad, tip, kalibrasyon_bitis) VALUES (?,?,?,?)",
                     (kod, ad, tip, (BUGUN + timedelta(days=gun)).isoformat()))
    conn.commit()

    adim = {kad: s for _, _, _, _, ks in PARCALAR for (kad, *_, s) in ks}
    sira = ["MB-125", "SN-50", "FP-400", "PM-12"]
    baslangic = datetime.combine(BUGUN - timedelta(days=44), datetime.min.time()).replace(hour=8)
    lot_sayac = {}
    is_emirleri = []
    ADET, ARALIK = 24, 1.8
    for i in range(ADET):
        parca = sira[i % 4] if i not in (ADET - 3, ADET - 2) else "MB-125"
        lot_sayac[parca] = lot_sayac.get(parca, 0) + 1
        is_emirleri.append({
            "is_emri_no": f"IE-2026-{1040 + i}", "parca_kodu": parca,
            "lot": f"L{(BUGUN - timedelta(days=44 - i * ARALIK)).strftime('%y%m%d')}-{parca.split('-')[0]}{lot_sayac[parca]:02d}",
            "adet": rnd.choice([20, 25, 40, 50, 60, 80]),
            "termin": (BUGUN - timedelta(days=36 - i * ARALIK)).isoformat(),
            "_sira": lot_sayac[parca], "_baslangic": baslangic + timedelta(days=i * ARALIK),
        })
    is_emirlerini_al(conn, [{k: v for k, v in e.items() if not k.startswith("_")} for e in is_emirleri])

    son = len(is_emirleri)
    for n, e in enumerate(is_emirleri):
        # son iş emirleri farklı aşamalarda kalsın
        if n >= son - 2:
            continue                                     # ERP'den yeni geldi, FAI bekliyor
        karantina = n == son - 3                         # aşınan delik: açık NCR ile karantinada
        proses_adedi = 1 if n in (son - 4, son - 5) else rnd.randint(3, 6)
        final = n < son - 5
        plan = ["FAI"] + ["PROSES"] * proses_adedi + (["FINAL"] if final else [])
        t = e["_baslangic"]
        karakteristikler = conn.execute(
            "SELECT k.*, p.kod parca_kod FROM karakteristik k JOIN parca p ON p.id = k.parca_id WHERE p.kod = ? ORDER BY k.no",
            (e["parca_kodu"],)).fetchall()
        j = 0
        deneme = 0
        while j < len(plan):
            tur = plan[j]
            t += timedelta(hours=rnd.randint(2, 7))
            gun = t.date().isoformat()
            olcumler = []
            for k in karakteristikler:
                adaylar = [a["id"] for a in conn.execute(
                    "SELECT id FROM alet WHERE tip = ? AND kalibrasyon_bitis >= ?", (k["alet_tipi"], gun))]
                s = adim[k["ad"]]
                deger = round(round(degeri_uret(rnd, k, e["_sira"], j, k["ad"]) / s) * s, 4)
                olcumler.append({"karakteristik_id": k["id"], "deger": deger, "alet_id": rnd.choice(adaylar)})
            muayene_kaydet(conn, e["is_emri_no"], tur, rnd.choice(PERSONEL), olcumler, t.strftime("%Y-%m-%d %H:%M"))
            durum = conn.execute("SELECT durum FROM is_emri WHERE no = ?", (e["is_emri_no"],)).fetchone()[0]
            if durum == "KARANTINA":
                if karantina:
                    break
                ie_id = conn.execute("SELECT id FROM is_emri WHERE no = ?", (e["is_emri_no"],)).fetchone()[0]
                for u in conn.execute(
                    "SELECT u.id, k.ad FROM uygunsuzluk u JOIN olcum o ON o.id = u.olcum_id "
                    "JOIN karakteristik k ON k.id = o.karakteristik_id WHERE u.is_emri_id = ? AND u.durum = 'ACIK'",
                    (ie_id,)).fetchall():
                    kok, aksiyon, karar = rnd.choice(KOK_NEDEN.get(u["ad"], VARSAYILAN_NEDEN))
                    t += timedelta(hours=rnd.randint(3, 20))
                    dof_kapat(conn, u["id"], kok, aksiyon, rnd.choice(["Mehmet Kaya", "Emre Şahin", "Zeynep Arslan"]), karar,
                              rnd.randint(1, 3) if karar == "HURDA" else 0, "Zeynep Arslan",
                              t.strftime("%Y-%m-%d %H:%M"))
                deneme += 1
                if tur in ("FAI", "FINAL") and deneme < 4:
                    continue                             # aynı adımı tekrarla
            j += 1
            deneme = 0
        # karantinadaki lotu kesin tolerans dışı bırak (demo hikâyesi)
        if karantina and conn.execute("SELECT durum FROM is_emri WHERE no = ?", (e["is_emri_no"],)).fetchone()[0] != "KARANTINA":
                t += timedelta(hours=3)
                olcumler = []
                for k in karakteristikler:
                    alt, ust = k["nominal"] + k["alt_sapma"], k["nominal"] + k["ust_sapma"]
                    deger = ust + 0.003 if "Pim deliği" in k["ad"] else round((alt + ust) / 2, 3)
                    aday = conn.execute("SELECT id FROM alet WHERE tip = ? AND kalibrasyon_bitis >= ?",
                                        (k["alet_tipi"], t.date().isoformat())).fetchone()[0]
                    olcumler.append({"karakteristik_id": k["id"], "deger": round(deger, 3), "alet_id": aday})
                muayene_kaydet(conn, e["is_emri_no"], "PROSES", "Emre Şahin", olcumler, t.strftime("%Y-%m-%d %H:%M"))

    # Geçmiş olaylar ERP'ye çoktan gitmiş olsun; son birkaçı kuyrukta beklesin, biri hata vermiş olsun
    son_id = conn.execute("SELECT MAX(id) FROM olay").fetchone()[0] or 0
    with conn:
        conn.execute("UPDATE olay SET durum='GONDERILDI', deneme=1, gonderilme=olusturma WHERE id <= ?", (son_id - 4,))
        conn.execute("UPDATE olay SET durum='HATA', deneme=2, son_hata=? WHERE id = ?",
                     ("<urlopen error timed out> (ERP 5 sn içinde yanıt vermedi)", son_id - 3))

    ozet = dict(conn.execute("SELECT durum, COUNT(*) FROM is_emri GROUP BY durum").fetchall())
    def sayi(sql):
        return conn.execute(sql).fetchone()[0]

    satirlar = [
        f"Veritabanı: {yol}",
        f"İş emirleri: {ozet}",
        f"Muayene: {sayi('SELECT COUNT(*) FROM muayene')} · Uygunsuzluk: {sayi('SELECT COUNT(*) FROM uygunsuzluk')}"
        f" (açık {sayi(ACIK_NCR)}) · Olay: {sayi('SELECT COUNT(*) FROM olay')}",
        "Kullanıcılar (parola: demo): " + ", ".join(k[0] for k in KULLANICILAR),
    ]
    metin = "\n".join(satirlar)
    conn.close()
    return metin


if __name__ == "__main__":
    from . import KOK

    print(kur(KOK / "veri" / "kalitehat.db"))
