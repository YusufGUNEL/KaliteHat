"""Yerel çalıştırma: veritabanı yoksa demo verisini kurar ve sunucuyu açar."""
from pathlib import Path

from kalitehat import create_app
from kalitehat.ornek_veri import kur

if __name__ == "__main__":
    app = create_app()
    if not Path(app.config["DB"]).exists():
        print(kur(app.config["DB"]))
    app.run(host="127.0.0.1", port=5050, threaded=True)
