"""Demo ERP alıcısı: gerçek ERP yokken webhook'un uçtan uca çalıştığını göstermek için.

Gerçek bir ERP'nin yapması gerekeni yapar: API anahtarını kontrol eder ve Idempotency-Key ile
aynı olayı ikinci kez işlemez. Üretimde KALITEHAT_DEMO_ERP=0 ile kapatılır.
"""
import hmac
import json
import sqlite3

from flask import Blueprint, current_app, jsonify, request

from ..ortak import simdi
from . import db

bp = Blueprint("demo_erp", __name__, url_prefix="/demo-erp")


@bp.post("/webhook")
def webhook():
    if not hmac.compare_digest(request.headers.get("X-API-Key", ""), current_app.config["API_ANAHTARI"]):
        return jsonify({"hata": "yetkisiz"}), 401
    anahtar = request.headers.get("Idempotency-Key", "")
    govde = request.get_json(silent=True) or {}
    if not anahtar or "tur" not in govde:
        return jsonify({"hata": "eksik"}), 400
    try:
        with db():
            db().execute(
                "INSERT INTO demo_erp_kutusu (alinma, anahtar, tur, veri) VALUES (?,?,?,?)",
                (simdi(), anahtar, govde["tur"], json.dumps(govde, ensure_ascii=False)),
            )
    except sqlite3.IntegrityError:
        return jsonify({"durum": "zaten işlendi"}), 200  # aynı olay tekrar geldi: yok say
    return jsonify({"durum": "işlendi"}), 200
