from flask import current_app, g

from ..db import baglan


def db():
    """İstek boyunca tek bağlantı; istek bitince kapanır."""
    if "conn" not in g:
        g.conn = baglan(current_app.config["DB"])
    return g.conn
