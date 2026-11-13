"""ERP'ye giden olaylar (transactional outbox).

Kalite durumu değiştiğinde olay, durum değişikliğiyle AYNI transaction içinde `olay` tablosuna yazılır.
Böylece "lot karantinaya alındı ama ERP'nin haberi olmadı" durumu oluşamaz. Teslim iki yoldan olur:
  1. Push: `gonder_bekleyenler` olayları ERP'nin webhook adresine POST eder; başarısızsa artan
     aralıklarla yeniden dener. Her olay sabit bir Idempotency-Key taşır, ERP aynı olayı iki kez
     alırsa ikincisini yok sayabilir (teslim en az bir kez garantilidir, tam bir kez değil).
  2. Pull: ERP `GET /api/v1/olaylar?sonra=<id>` ile kaldığı yerden okur.
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from .ortak import simdi

TURLER = {
    "FAI_ONAYLANDI": "İlk parça onaylandı; seri üretim serbest",
    "LOT_KARANTINAYA_ALINDI": "Lot karantinada; sevk ve stok kullanımı bloke",
    "LOT_KARANTINADAN_CIKTI": "Açık uygunsuzluk kalmadı; lot üretime döndü",
    "HURDA_BILDIRILDI": "Hurda adedi; ERP stoktan düşer, gerekirse yeniden iş emri açar",
    "LOT_SEVKE_UYGUN": "Final muayene geçti; lot sevk edilebilir",
}
EN_FAZLA_DENEME = 6


def yaz(conn, tur, is_emri_no, veri, zaman=None):
    assert tur in TURLER, tur
    conn.execute(
        "INSERT INTO olay (tur, is_emri_no, veri, olusturma, sonraki_deneme) VALUES (?,?,?,?,?)",
        (tur, is_emri_no, json.dumps(veri, ensure_ascii=False), zaman or simdi(), zaman or simdi()),
    )


def disa_ver(olay):
    """Olayın ERP'ye giden biçimi. Push ve pull aynı şekli kullanır."""
    return {
        "olay_id": olay["id"],
        "anahtar": f"kalitehat-olay-{olay['id']}",
        "tur": olay["tur"],
        "is_emri_no": olay["is_emri_no"],
        "zaman": olay["olusturma"],
        "veri": json.loads(olay["veri"]),
    }


def http_gonder(url, govde, anahtar, api_anahtari=None, zaman_asimi=5):
    """2xx dışı her yanıt ve ağ hatası istisna fırlatır."""
    istek = urllib.request.Request(
        url,
        data=json.dumps(govde, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Idempotency-Key": anahtar,
                 **({"X-API-Key": api_anahtari} if api_anahtari else {})},
        method="POST",
    )
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as yanit:
        if not 200 <= yanit.status < 300:
            raise urllib.error.HTTPError(url, yanit.status, "beklenmeyen yanıt", yanit.headers, None)


def gonder_bekleyenler(conn, url, gonderici=http_gonder, an=None, api_anahtari=None):
    """Zamanı gelmiş olayları gönderir. {"gonderilen": n, "hatali": n} döner."""
    an = an or datetime.now()
    an_str = an.strftime("%Y-%m-%d %H:%M")
    sonuc = {"gonderilen": 0, "hatali": 0}
    bekleyenler = conn.execute(
        "SELECT * FROM olay WHERE durum IN ('BEKLIYOR', 'HATA') AND sonraki_deneme <= ? ORDER BY id", (an_str,)
    ).fetchall()
    for olay in bekleyenler:
        govde = disa_ver(olay)
        try:
            gonderici(url, govde, govde["anahtar"], api_anahtari)
        except Exception as e:  # ağ, zaman aşımı, 4xx/5xx: hepsi yeniden denenir
            deneme = olay["deneme"] + 1
            # 1, 2, 4, 8, 16 dakika sonra tekrar; sonra vazgeç ve elle müdahale iste
            durum = "VAZGECILDI" if deneme >= EN_FAZLA_DENEME else "HATA"
            sonraki = (an + timedelta(minutes=2 ** (deneme - 1))).strftime("%Y-%m-%d %H:%M")
            with conn:
                conn.execute(
                    "UPDATE olay SET durum=?, deneme=?, sonraki_deneme=?, son_hata=? WHERE id=?",
                    (durum, deneme, sonraki, str(e)[:300], olay["id"]),
                )
            sonuc["hatali"] += 1
            continue
        with conn:
            conn.execute(
                "UPDATE olay SET durum='GONDERILDI', deneme=deneme+1, gonderilme=?, son_hata=NULL WHERE id=?",
                (an_str, olay["id"]),
            )
        sonuc["gonderilen"] += 1
    return sonuc


def yeniden_kuyruga_al(conn, olay_id):
    with conn:
        conn.execute(
            "UPDATE olay SET durum='BEKLIYOR', deneme=0, sonraki_deneme=?, son_hata=NULL "
            "WHERE id=? AND durum IN ('HATA', 'VAZGECILDI')",
            (simdi(), olay_id),
        )
