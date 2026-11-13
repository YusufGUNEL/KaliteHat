import sqlite3

SEMA = """
CREATE TABLE IF NOT EXISTS parca (
    id INTEGER PRIMARY KEY,
    kod TEXT UNIQUE NOT NULL,
    ad TEXT NOT NULL,
    revizyon TEXT NOT NULL,
    malzeme TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS karakteristik (
    id INTEGER PRIMARY KEY,
    parca_id INTEGER NOT NULL REFERENCES parca(id),
    no INTEGER NOT NULL,
    ad TEXT NOT NULL,
    nominal REAL NOT NULL,
    alt_sapma REAL NOT NULL,
    ust_sapma REAL NOT NULL,
    birim TEXT NOT NULL,
    alet_tipi TEXT NOT NULL,
    kritik INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alet (
    id INTEGER PRIMARY KEY,
    kod TEXT UNIQUE NOT NULL,
    ad TEXT NOT NULL,
    tip TEXT NOT NULL,
    kalibrasyon_bitis TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS is_emri (
    id INTEGER PRIMARY KEY,
    no TEXT UNIQUE NOT NULL,
    parca_id INTEGER NOT NULL REFERENCES parca(id),
    lot TEXT NOT NULL,
    adet INTEGER NOT NULL,
    termin TEXT,
    durum TEXT NOT NULL DEFAULT 'FAI_BEKLIYOR',
    fai_onayli INTEGER NOT NULL DEFAULT 0,
    hurda_adet INTEGER NOT NULL DEFAULT 0,
    kaynak TEXT NOT NULL DEFAULT 'ERP',
    olusturma TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS muayene (
    id INTEGER PRIMARY KEY,
    is_emri_id INTEGER NOT NULL REFERENCES is_emri(id),
    tur TEXT NOT NULL,
    numune_no INTEGER NOT NULL,
    personel TEXT NOT NULL,
    tarih TEXT NOT NULL,
    sonuc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS olcum (
    id INTEGER PRIMARY KEY,
    muayene_id INTEGER NOT NULL REFERENCES muayene(id),
    karakteristik_id INTEGER NOT NULL REFERENCES karakteristik(id),
    deger REAL NOT NULL,
    alet_id INTEGER NOT NULL REFERENCES alet(id),
    uygun INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS uygunsuzluk (
    id INTEGER PRIMARY KEY,
    is_emri_id INTEGER NOT NULL REFERENCES is_emri(id),
    olcum_id INTEGER NOT NULL REFERENCES olcum(id),
    aciklama TEXT NOT NULL,
    acilis TEXT NOT NULL,
    durum TEXT NOT NULL DEFAULT 'ACIK',
    kok_neden TEXT,
    aksiyon TEXT,
    sorumlu TEXT,
    karar TEXT,
    hurda_adet INTEGER NOT NULL DEFAULT 0,
    kapanis TEXT
);
"""


def baglan(yol):
    conn = sqlite3.connect(yol)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SEMA)
    return conn
