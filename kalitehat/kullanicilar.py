"""Kullanıcılar ve roller. Kayıtlardaki "kim yaptı" bilgisi elle yazılmaz, oturumdan gelir."""
from werkzeug.security import check_password_hash, generate_password_hash

ROLLER = {
    "OPERATOR": "Operatör",
    "KALITE": "Kalite",
    "YONETICI": "Yönetici",
}
# Hangi rol neyi yapabilir
YETKILER = {
    "muayene": {"OPERATOR", "KALITE", "YONETICI"},
    "dof": {"KALITE", "YONETICI"},
    "kalibrasyon": {"KALITE", "YONETICI"},
    "erp_ice_aktar": {"KALITE", "YONETICI"},
    "entegrasyon": {"YONETICI"},
}


def ekle(conn, kullanici_adi, ad, rol, parola):
    assert rol in ROLLER
    with conn:
        conn.execute(
            "INSERT INTO kullanici (kullanici_adi, ad, rol, parola_ozeti) VALUES (?,?,?,?)",
            (kullanici_adi, ad, rol, generate_password_hash(parola)),
        )


def dogrula(conn, kullanici_adi, parola):
    k = conn.execute("SELECT * FROM kullanici WHERE kullanici_adi = ?", ((kullanici_adi or "").strip(),)).fetchone()
    if k is None or not check_password_hash(k["parola_ozeti"], parola or ""):
        return None
    return k


def yetkili_mi(rol, is_):
    return rol in YETKILER[is_]
