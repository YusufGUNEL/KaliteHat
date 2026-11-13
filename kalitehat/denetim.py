"""Denetim izi: kim, ne zaman, neyi değiştirdi. AS9100 kayıt kontrolü için silinmez, güncellenmez."""
import json

from .ortak import simdi


def kaydet(conn, kullanici, eylem, varlik, varlik_id, ayrinti=None, zaman=None):
    conn.execute(
        "INSERT INTO denetim (zaman, kullanici, eylem, varlik, varlik_id, ayrinti) VALUES (?,?,?,?,?,?)",
        (zaman or simdi(), kullanici, eylem, varlik, str(varlik_id),
         json.dumps(ayrinti, ensure_ascii=False) if ayrinti else None),
    )
