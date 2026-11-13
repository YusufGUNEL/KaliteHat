"""KaliteHat — CNC atölyesi için kalite kontrol ve ERP köprüsü."""
import os
import secrets
from pathlib import Path

import click
from flask import Flask, g

__version__ = "1.0.0"

KOK = Path(__file__).resolve().parent.parent


def create_app(ayarlar=None):
    app = Flask(__name__)
    app.config.update(
        DB=os.environ.get("KALITEHAT_DB", str(KOK / "veri" / "kalitehat.db")),
        SECRET_KEY=os.environ.get("KALITEHAT_GIZLI_ANAHTAR") or secrets.token_hex(32),
        API_ANAHTARI=os.environ.get("KALITEHAT_API_ANAHTARI", "demo-api-anahtari"),
        ERP_WEBHOOK=os.environ.get("KALITEHAT_ERP_WEBHOOK", ""),
        DEMO_ERP=os.environ.get("KALITEHAT_DEMO_ERP", "1") == "1",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )
    if ayarlar:
        app.config.update(ayarlar)

    @app.teardown_appcontext
    def baglantiyi_kapat(_):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    from .web import api, arayuz, demo_erp, guvenlik

    guvenlik.kur(app)
    app.register_blueprint(arayuz.bp)
    app.register_blueprint(api.bp)
    if app.config["DEMO_ERP"]:
        app.register_blueprint(demo_erp.bp)

    @app.cli.command("olaylari-gonder")
    def olaylari_gonder():
        """Bekleyen ERP olaylarını webhook adresine gönderir (zamanlanmış görev olarak çalıştırılır)."""
        from . import olaylar
        from .db import baglan

        url = app.config["ERP_WEBHOOK"]
        if not url:
            raise click.ClickException("KALITEHAT_ERP_WEBHOOK tanımlı değil.")
        conn = baglan(app.config["DB"])
        click.echo(olaylar.gonder_bekleyenler(conn, url, api_anahtari=app.config["API_ANAHTARI"]))

    @app.cli.command("ornek-veri")
    def ornek_veri_kur():
        """Veritabanını silip demo verisiyle yeniden kurar."""
        from .ornek_veri import kur

        click.echo(kur(app.config["DB"]))

    return app
