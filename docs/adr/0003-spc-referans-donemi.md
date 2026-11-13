# ADR-0003: SPC kontrol sınırları referans dönemden hesaplanır

- Durum: Kabul edildi
- Tarih: 2026-11-14

## Bağlam

Kontrol sınırları tüm veriden hesaplanırsa, takım aşınması gibi yavaş bir kayma ortalamayı ve sınırları da yanında sürükler; grafik kaymayı geç ya da hiç göstermez.

## Karar

- I-MR sınırları ilk 20 ölçümden (referans dönem) hesaplanır ve sabit tutulur. Daha az veri varsa mevcut verinin tamamı kullanılır.
- Grafik referans dönemi gri bantla gösterir.
- Yeterlilik ise iki biçimde verilir: Cp/Cpk (σ_iç = MR̄ / 1,128) ve Pp/Ppk (tüm verinin standart sapması).

## Sonuçlar

- Demo verisindeki pim deliği aşınması, ölçüm tolerans dışına çıkmadan 18 ölçüm önce uyarı verir.
- Proses bilinçli olarak değiştirildiğinde (yeni takım, yeni fikstür) referans dönemin yeniden başlatılması gerekir. Bu sürümde bunun için ayrı bir ekran yoktur.
