"""SQLite bağlantısı ve sıralı şema göçleri (PRAGMA user_version ile)."""
import sqlite3

GOCLER = [
    # 1 — çekirdek: ana veri, iş emri, muayene, uygunsuzluk
    """
    CREATE TABLE parca (
        id INTEGER PRIMARY KEY,
        kod TEXT UNIQUE NOT NULL,
        ad TEXT NOT NULL,
        revizyon TEXT NOT NULL,
        malzeme TEXT NOT NULL
    );
    CREATE TABLE karakteristik (
        id INTEGER PRIMARY KEY,
        parca_id INTEGER NOT NULL REFERENCES parca(id),
        no INTEGER NOT NULL,
        ad TEXT NOT NULL,
        nominal REAL NOT NULL,
        alt_sapma REAL NOT NULL,
        ust_sapma REAL NOT NULL,
        birim TEXT NOT NULL,
        alet_tipi TEXT NOT NULL,
        kritik INTEGER NOT NULL DEFAULT 0,
        UNIQUE (parca_id, no)
    );
    CREATE TABLE alet (
        id INTEGER PRIMARY KEY,
        kod TEXT UNIQUE NOT NULL,
        ad TEXT NOT NULL,
        tip TEXT NOT NULL,
        kalibrasyon_bitis TEXT NOT NULL
    );
    CREATE TABLE is_emri (
        id INTEGER PRIMARY KEY,
        no TEXT UNIQUE NOT NULL,
        parca_id INTEGER NOT NULL REFERENCES parca(id),
        lot TEXT NOT NULL,
        adet INTEGER NOT NULL CHECK (adet > 0),
        termin TEXT,
        durum TEXT NOT NULL DEFAULT 'FAI_BEKLIYOR'
            CHECK (durum IN ('FAI_BEKLIYOR', 'URETIMDE', 'KARANTINA', 'ONAYLI')),
        fai_onayli INTEGER NOT NULL DEFAULT 0,
        hurda_adet INTEGER NOT NULL DEFAULT 0,
        kaynak TEXT NOT NULL DEFAULT 'ERP',
        olusturma TEXT NOT NULL
    );
    CREATE TABLE muayene (
        id INTEGER PRIMARY KEY,
        is_emri_id INTEGER NOT NULL REFERENCES is_emri(id),
        tur TEXT NOT NULL CHECK (tur IN ('FAI', 'PROSES', 'FINAL')),
        numune_no INTEGER NOT NULL,
        personel TEXT NOT NULL,
        tarih TEXT NOT NULL,
        sonuc TEXT NOT NULL CHECK (sonuc IN ('UYGUN', 'RED'))
    );
    CREATE TABLE olcum (
        id INTEGER PRIMARY KEY,
        muayene_id INTEGER NOT NULL REFERENCES muayene(id),
        karakteristik_id INTEGER NOT NULL REFERENCES karakteristik(id),
        deger REAL NOT NULL,
        alet_id INTEGER NOT NULL REFERENCES alet(id),
        uygun INTEGER NOT NULL
    );
    CREATE TABLE uygunsuzluk (
        id INTEGER PRIMARY KEY,
        is_emri_id INTEGER NOT NULL REFERENCES is_emri(id),
        olcum_id INTEGER NOT NULL REFERENCES olcum(id),
        aciklama TEXT NOT NULL,
        acilis TEXT NOT NULL,
        durum TEXT NOT NULL DEFAULT 'ACIK' CHECK (durum IN ('ACIK', 'KAPALI')),
        kok_neden TEXT,
        aksiyon TEXT,
        sorumlu TEXT,
        karar TEXT,
        hurda_adet INTEGER NOT NULL DEFAULT 0,
        kapanis TEXT
    );
    CREATE INDEX ix_olcum_karakteristik ON olcum(karakteristik_id);
    CREATE INDEX ix_muayene_is_emri ON muayene(is_emri_id);
    """,
    # 2 — entegrasyon ve kayıt: ERP'ye giden olaylar (outbox) ve denetim izi
    """
    CREATE TABLE olay (
        id INTEGER PRIMARY KEY,
        tur TEXT NOT NULL,
        is_emri_no TEXT NOT NULL,
        veri TEXT NOT NULL,
        olusturma TEXT NOT NULL,
        durum TEXT NOT NULL DEFAULT 'BEKLIYOR' CHECK (durum IN ('BEKLIYOR', 'GONDERILDI', 'HATA', 'VAZGECILDI')),
        deneme INTEGER NOT NULL DEFAULT 0,
        sonraki_deneme TEXT,
        son_hata TEXT,
        gonderilme TEXT
    );
    CREATE INDEX ix_olay_durum ON olay(durum, sonraki_deneme);
    CREATE TABLE denetim (
        id INTEGER PRIMARY KEY,
        zaman TEXT NOT NULL,
        kullanici TEXT NOT NULL,
        eylem TEXT NOT NULL,
        varlik TEXT NOT NULL,
        varlik_id TEXT NOT NULL,
        ayrinti TEXT
    );
    CREATE TABLE kullanici (
        id INTEGER PRIMARY KEY,
        kullanici_adi TEXT UNIQUE NOT NULL,
        ad TEXT NOT NULL,
        rol TEXT NOT NULL CHECK (rol IN ('OPERATOR', 'KALITE', 'YONETICI')),
        parola_ozeti TEXT NOT NULL
    );
    CREATE TABLE demo_erp_kutusu (
        id INTEGER PRIMARY KEY,
        alinma TEXT NOT NULL,
        anahtar TEXT UNIQUE NOT NULL,
        tur TEXT NOT NULL,
        veri TEXT NOT NULL
    );
    """,
]


def baglan(yol: str) -> sqlite3.Connection:
    conn = sqlite3.connect(yol)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    goc_uygula(conn)
    return conn


def goc_uygula(conn: sqlite3.Connection) -> None:
    surum = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(GOCLER[surum:], start=surum + 1):
        conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {i};\nCOMMIT;")
