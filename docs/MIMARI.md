# Mimari

## Bağlam

```
           iş emri (API / CSV / XLSX)                 kalite olayları (webhook)
  ┌─────┐ ─────────────────────────────▶ ┌───────────┐ ─────────────────────────▶ ┌─────┐
  │ ERP │                                 │ KaliteHat │                             │ ERP │
  └─────┘ ◀───────────────────────────── └───────────┘ ◀─────────────────────────  └─────┘
           kalite özeti (GET)                   ▲        olay akışı (GET, imleçle)
                                                │ tarayıcı
                                   operatör · kalite · yönetici
```

KaliteHat iş emrinin sahibi değildir; iş emri ERP'de doğar. KaliteHat'ın sahibi olduğu şey **kalite kararıdır**: lot ilk parçadan geçti mi, karantinada mı, sevke uygun mu. ERP bu kararı ya webhook ile alır ya da sorarak öğrenir.

## Katmanlar

```
web/arayuz.py   web/api.py   web/demo_erp.py      HTTP: form, JSON, yetki, CSRF
        │            │
        ▼            ▼
muayene.py  dof.py  erp.py  spc.py  fai_rapor.py  iş kuralları (Flask'tan bağımsız)
        │            │
        ▼            ▼
olaylar.py (outbox)  denetim.py (iz)              yan kayıtlar, aynı transaction
        │
        ▼
db.py  →  SQLite
```

İş kuralları modülleri yalnızca bir `sqlite3.Connection` alır; Flask'ı bilmez. Bu yüzden testler HTTP olmadan doğrudan kurallara gider (`tests/test_kurallar.py`), web katmanı ince kalır.

## Lot durum makinesi

```
           FAI uygun                  final uygun
FAI_BEKLIYOR ─────────▶ URETIMDE ─────────────────▶ ONAYLI
     │                     │
     │ tolerans dışı       │ tolerans dışı
     ▼                     ▼
  KARANTINA ◀──────────────┘
     │
     │ son açık DÖF kapandı
     ▼
 (FAI onaylıysa URETIMDE, değilse FAI_BEKLIYOR)
```

Kurallar `muayene._kapiyi_kontrol_et` içinde:

- FAI onaylanmadan proses/final muayene yapılamaz.
- Açık uygunsuzluk varken final muayene yapılamaz.
- `ONAYLI` lota yeni muayene girilmez.
- Kalibrasyonu geçmiş aletle ölçüm kaydedilmez.

## Bir muayenenin yolculuğu

`muayene_kaydet` önce her şeyi doğrular (iş emri, kapı, karakteristik, alet, kalibrasyon). Hiçbir şey yazmadan hata verebilmek için doğrulama yazmadan önce yapılır. Sonra tek `with conn:` bloğu içinde:

1. `muayene` ve `olcum` satırları yazılır.
2. Tolerans dışı her ölçüm için `uygunsuzluk` açılır.
3. Lot durumu güncellenir.
4. Duruma göre `olay` yazılır (outbox): `FAI_ONAYLANDI`, `LOT_KARANTINAYA_ALINDI` (yalnızca geçişte), `LOT_SEVKE_UYGUN`.
5. `denetim` kaydı yazılır.

Bunlardan biri başarısız olursa hepsi geri alınır. Lot karantinaya girip ERP'ye haber gitmemesi mümkün değildir.

## ERP'ye teslim

- **Push:** `olaylar.gonder_bekleyenler` zamanı gelmiş `BEKLIYOR`/`HATA` olayları gönderir. Başarısız gönderimde 1, 2, 4, 8, 16 dakika sonra tekrar denenir. 6. denemeden sonra `VAZGECILDI` olur ve "ERP olayları" ekranından elle kuyruğa alınır.
- **Teslim garantisi:** en az bir kez. Her olay sabit `Idempotency-Key: kalitehat-olay-<id>` taşır; alıcı aynı anahtarı ikinci kez görürse işlemez (demo alıcı bunu `UNIQUE` kısıtıyla yapar).
- **Pull:** `GET /api/v1/olaylar?sonra=<id>` olayları sırayla döner, `sonraki_imlec` ile devam edilir. Push kapalı bir ağda ERP yalnızca çekerek de çalışabilir.

## SPC

- Tekil ölçüm (alt grup = 1), bu yüzden I-MR grafiği.
- σ_iç = MR̄ / 1,128. Kontrol sınırları ilk 20 ölçümden (referans dönem) hesaplanıp sabit tutulur; tüm veriden hesaplansaydı yavaş kayma ortalamayı da sürükleyip kendini gizlerdi.
- Cp/Cpk σ_iç ile (kısa dönem), Pp/Ppk tüm verinin standart sapmasıyla (uzun dönem). İkisi arasındaki büyük fark zamana bağlı bir neden (aşınma, ısınma) gösterir.
- Kurallar: 1) ±3σ dışı nokta, 2) 9 nokta aynı tarafta, 3) 6 nokta sürekli artan/azalan.

## Güvenlik

- Arayüz: oturum girişi (werkzeug parola özeti), girişte oturum yenilenir, `HttpOnly` + `SameSite=Lax` çerez.
- Her form POST'u CSRF jetonu ister. API uçları jeton yerine `X-API-Key` ister (`hmac.compare_digest`).
- Yetki: `kullanicilar.YETKILER` tablosu. Operatör DÖF kapatamaz, kalibrasyon yenileyemez.
- Girişten sonra yönlendirme yalnızca uygulama içi yollara yapılır (açık yönlendirme engeli).
- Yükleme boyutu 5 MB ile sınırlıdır.

## Veri modeli

| Tablo | Ne tutar |
|---|---|
| `parca`, `karakteristik` | Kontrol planı: nominal, alt/üst sapma, kritik mi, hangi alet tipiyle ölçülür |
| `alet` | Ölçüm aleti ve kalibrasyon bitiş tarihi |
| `is_emri` | ERP'den gelen iş emri, lot, adet, durum, hurda adedi |
| `muayene`, `olcum` | Kim, ne zaman, hangi aletle, ne ölçtü |
| `uygunsuzluk` | NCR, DÖF alanları, ürün kararı |
| `olay` | Outbox: tür, veri, teslim durumu, deneme sayısı |
| `denetim` | Denetim izi |
| `kullanici` | Ad, rol, parola özeti |

Şema `db.GOCLER` listesinde sürümlüdür; `PRAGMA user_version` hangi geçişin uygulandığını tutar.

## Bilinçli sınırlar

- SQLite tek yazıcıya izin verir; bir atölyenin muayene trafiği için yeterlidir. Çok tezgâhlı, eşzamanlı yoğun kullanımda PostgreSQL'e geçiş SQL'i büyük ölçüde değiştirmez (bkz. ADR-0001).
- Olay gönderimi istek içinde değil, zamanlanmış komutla (`flask olaylari-gonder`) ya da ekrandaki düğmeyle yapılır; ayrı bir kuyruk sunucusu gerekmez.
