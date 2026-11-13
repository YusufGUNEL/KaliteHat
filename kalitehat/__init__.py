from pathlib import Path

from flask import Flask, g


def create_app(db_yolu=None):
    app = Flask(__name__)
    app.config["DB"] = db_yolu or str(Path(__file__).resolve().parent.parent / "veri" / "kalitehat.db")
    app.secret_key = "yerel-demo"

    @app.teardown_appcontext
    def kapat(_):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    from . import web

    app.register_blueprint(web.bp)
    return app
