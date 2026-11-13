# ADR-0001: Flask + SQLite, ORM yok

- Durum: Kabul edildi
- Tarih: 2026-11-14

## Bağlam

Uygulama tek atölyede çalışan bir kalite birimi içindir: birkaç operatör, bir-iki kalite personeli, bir ERP. Kurulumun bir Windows sunucuda ya da tek konteynerde, ayrı bir veritabanı sunucusu olmadan çalışması istenir.

## Karar

- Web katmanı Flask, veritabanı SQLite (`foreign_keys` açık).
- ORM kullanılmaz; sorgular düz SQL ve parametreli. Şema `db.GOCLER` içinde sürümlü, `PRAGMA user_version` ile uygulanır.
- İş kuralları `sqlite3.Connection` alan düz fonksiyonlardır; Flask'a bağımlı değildir.

## Sonuçlar

- Kurulum `pip install` + tek dosya. Yedek = dosya kopyası.
- Tek yazıcı sınırı var. Muayene trafiği (dakikada birkaç kayıt) için sorun değil.
- Yük artarsa PostgreSQL'e geçiş: SQL standart tutulduğu için değişiklik `db.py` ve birkaç tarih fonksiyonuyla sınırlı kalır.
