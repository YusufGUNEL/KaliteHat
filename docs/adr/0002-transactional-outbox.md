# ADR-0002: ERP'ye bildirim için transactional outbox

- Durum: Kabul edildi
- Tarih: 2026-11-14

## Bağlam

Lot karantinaya alındığında ERP'nin bunu bilmesi gerekir; yoksa karantinadaki parça sevk edilebilir ya da stokta kullanılabilir. Muayene kaydedilirken ERP'ye doğrudan HTTP çağrısı yapmanın iki sorunu var:

1. ERP kapalıysa ya kalite kaydı da reddedilir (atölye durur) ya da kayıt yapılır ama ERP'nin haberi olmaz.
2. Kayıt ile çağrı arasında süreç çökerse durum belirsiz kalır.

## Karar

- Durum değişikliği ve `olay` satırı aynı veritabanı transaction'ında yazılır.
- Ayrı bir gönderici olayları ERP webhook'una iletir. Her olay sabit bir `Idempotency-Key` taşır.
- Başarısız gönderimler 1, 2, 4, 8, 16 dakika arayla denenir; 6 denemeden sonra `VAZGECILDI` olur ve ekrandan elle yeniden kuyruğa alınır.
- ERP ayrıca `GET /api/v1/olaylar?sonra=<id>` ile olayları kendisi çekebilir.

## Sonuçlar

- Kalite kaydı ERP'nin ayakta olmasına bağlı değildir.
- Teslim "en az bir kez"dir; ERP tarafı anahtara göre tekrarı yok saymalıdır.
- Olay sırası kimlik sırasıdır; pull ile okuyan taraf kaldığı yeri imleçle tutar.
