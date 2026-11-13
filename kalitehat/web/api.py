"""ERP'nin konuştuğu REST API (v1). Kimlik doğrulama: X-API-Key başlığı.

Hata biçimi her uçta aynıdır: {"hata": {"kod": "...", "mesaj": "...", "ayrinti": ...}}
"""
import hmac

from flask import Blueprint, current_app, jsonify, request

from .. import erp, olaylar
from ..ortak import KuralHatasi
from . import db
from .openapi import SPEC

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def hata(status, kod, mesaj, ayrinti=None):
    govde = {"hata": {"kod": kod, "mesaj": mesaj}}
    if ayrinti is not None:
        govde["hata"]["ayrinti"] = ayrinti
    return jsonify(govde), status


@bp.before_request
def anahtar_kontrol():
    if request.endpoint == "api.openapi":
        return None
    beklenen = current_app.config["API_ANAHTARI"]
    if not hmac.compare_digest(request.headers.get("X-API-Key", ""), beklenen):
        return hata(401, "YETKISIZ", "Geçerli bir X-API-Key başlığı gerekli.")
    return None


@bp.errorhandler(404)
def bulunamadi(_):
    return hata(404, "BULUNAMADI", "Kaynak bulunamadı.")


@bp.post("/is-emirleri")
def is_emri_al():
    veri = request.get_json(silent=True)
    if isinstance(veri, dict):
        veri = [veri]
    if not isinstance(veri, list) or not veri or not all(isinstance(v, dict) for v in veri):
        return hata(400, "GECERSIZ_GOVDE", "JSON nesne ya da boş olmayan nesne listesi bekleniyor.")
    if len(veri) > 500:
        return hata(413, "COK_BUYUK", "Tek istekte en fazla 500 iş emri gönderilebilir.")
    sonuc = erp.is_emirlerini_al(db(), veri, kaynak="ERP API", kullanici="ERP API")
    govde = {"eklenen": sonuc["eklenen"],
             "atlanan": [{"is_emri_no": n, "sebep": s} for n, s in sonuc["atlanan"]]}
    return jsonify(govde), 201 if sonuc["eklenen"] else 200


@bp.get("/is-emirleri")
def is_emri_listesi():
    try:
        sayfa = max(1, int(request.args.get("sayfa", 1)))
        boyut = min(200, max(1, int(request.args.get("boyut", 50))))
    except ValueError:
        return hata(400, "GECERSIZ_PARAMETRE", "sayfa ve boyut tam sayı olmalı.")
    durum = request.args.get("durum")
    kosul, args = ("WHERE durum = ?", (durum,)) if durum else ("", ())
    conn = db()
    toplam = conn.execute(f"SELECT COUNT(*) FROM is_emri {kosul}", args).fetchone()[0]
    nolar = [r[0] for r in conn.execute(
        f"SELECT no FROM is_emri {kosul} ORDER BY id DESC LIMIT ? OFFSET ?", (*args, boyut, (sayfa - 1) * boyut)
    )]
    return jsonify({
        "veri": [erp.kalite_ozeti(conn, n) for n in nolar],
        "sayfalama": {"sayfa": sayfa, "boyut": boyut, "toplam": toplam, "sayfa_sayisi": -(-toplam // boyut)},
    })


@bp.get("/is-emirleri/<no>")
def is_emri_kalite(no):
    try:
        return jsonify(erp.kalite_ozeti(db(), no))
    except KuralHatasi as e:
        return hata(404, "BULUNAMADI", str(e))


@bp.get("/olaylar")
def olay_akisi():
    """Pull modeli: ERP en son işlediği olay_id'yi `sonra` ile verir, yenileri alır."""
    try:
        sonra = int(request.args.get("sonra", 0))
        limit = min(500, max(1, int(request.args.get("limit", 100))))
    except ValueError:
        return hata(400, "GECERSIZ_PARAMETRE", "sonra ve limit tam sayı olmalı.")
    satirlar = db().execute("SELECT * FROM olay WHERE id > ? ORDER BY id LIMIT ?", (sonra, limit)).fetchall()
    veri = [olaylar.disa_ver(o) for o in satirlar]
    return jsonify({"veri": veri, "sonraki_imlec": veri[-1]["olay_id"] if veri else sonra})


@bp.get("/openapi.json")
def openapi():
    return jsonify(SPEC)
