"""Oturum, rol kontrolü ve CSRF koruması (ek bağımlılık olmadan)."""
import hmac
import secrets
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

from .. import kullanicilar
from . import db

ACIK_UCLAR = {"arayuz.giris", "static"}


def kur(app):
    @app.before_request
    def oturum_ve_csrf():
        g.kullanici = None
        if session.get("kid"):
            g.kullanici = db().execute("SELECT * FROM kullanici WHERE id = ?", (session["kid"],)).fetchone()

        # API ve demo ERP kendi doğrulamasını yapar (API anahtarı); tarayıcı oturumu kullanmaz
        if request.blueprint in ("api", "demo_erp"):
            return None
        if request.method == "POST":
            beklenen = session.get("csrf", "")
            gelen = request.form.get("csrf", "")
            if not beklenen or not hmac.compare_digest(beklenen, gelen):
                abort(400, "Form süresi dolmuş ya da geçersiz (CSRF). Sayfayı yenileyip tekrar deneyin.")
        if g.kullanici is None and request.endpoint not in ACIK_UCLAR:
            return redirect(url_for("arayuz.giris", sonra=request.full_path))
        return None

    @app.context_processor
    def sablon_degiskenleri():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return {
            "csrf": session["csrf"],
            "kullanici": g.get("kullanici"),
            "ROLLER": kullanicilar.ROLLER,
            "yetkili": lambda is_: g.get("kullanici") is not None
            and kullanicilar.yetkili_mi(g.kullanici["rol"], is_),
        }


def yetki(is_):
    """Rolü bu işe yetmeyen kullanıcıyı geri gönderir."""

    def sarmala(f):
        @wraps(f)
        def ic(*a, **kw):
            if not kullanicilar.yetkili_mi(g.kullanici["rol"], is_):
                flash(f"Bu işlem için yetkiniz yok ({kullanicilar.ROLLER[g.kullanici['rol']]}).", "hata")
                return redirect(request.referrer or url_for("arayuz.pano"))
            return f(*a, **kw)

        return ic

    return sarmala
