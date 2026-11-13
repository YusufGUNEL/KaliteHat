from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, url_for

from . import kurallar
from .db import baglan
from .erp import dosya_oku, is_emirlerini_al
from .kurallar import KuralHatasi

bp = Blueprint("web", __name__)

DURUM_ADI = {
    "FAI_BEKLIYOR": "İlk parça bekliyor",
    "URETIMDE": "Üretimde",
    "KARANTINA": "Karantina",
    "ONAYLI": "Onaylı · sevke hazır",
}
KARAR_ADI = {"YENIDEN_ISLEME": "Yeniden işleme", "SAPMA_KABUL": "Sapma ile kabul", "HURDA": "Hurda"}
TUR_ADI = {"FAI": "İlk parça (FAI)", "PROSES": "Proses", "FINAL": "Final"}


def db():
    if "conn" not in g:
        g.conn = baglan(current_app.config["DB"])
    return g.conn


@bp.app_context_processor
def sabitler():
    return {"DURUM_ADI": DURUM_ADI, "KARAR_ADI": KARAR_ADI, "TUR_ADI": TUR_ADI, "bugun": kurallar.bugun()}


@bp.app_template_filter("tol")
def tol(k):
    a, u = k["alt_sapma"], k["ust_sapma"]
    if a == -u:
        return f"{k['nominal']:g} ±{u:g}"
    isaretli = lambda x: "0" if x == 0 else f"{x:+g}"
    return f"{k['nominal']:g} {isaretli(u)} / {isaretli(a)}"


# ---------- pano ----------

def karakteristik_degerleri(conn, kid):
    return [r[0] for r in conn.execute(
        "SELECT o.deger FROM olcum o JOIN muayene m ON m.id = o.muayene_id WHERE o.karakteristik_id = ? ORDER BY m.tarih, o.id",
        (kid,),
    )]


@bp.get("/")
def pano():
    conn = db()
    sayilar = {r["durum"]: r["n"] for r in conn.execute("SELECT durum, COUNT(*) n FROM is_emri GROUP BY durum")}
    acik_dof = conn.execute("SELECT COUNT(*) FROM uygunsuzluk WHERE durum='ACIK'").fetchone()[0]
    m = conn.execute(
        "SELECT COUNT(*) toplam, SUM(sonuc='RED') red FROM muayene WHERE tarih >= date('now','-30 day')"
    ).fetchone()
    ret_orani = (m["red"] or 0) / m["toplam"] * 100 if m["toplam"] else 0

    pareto = conn.execute(
        "SELECT p.kod || ' · ' || k.ad etiket, COUNT(*) n FROM uygunsuzluk u "
        "JOIN olcum o ON o.id = u.olcum_id JOIN karakteristik k ON k.id = o.karakteristik_id "
        "JOIN parca p ON p.id = k.parca_id GROUP BY k.id ORDER BY n DESC"
    ).fetchall()
    toplam = sum(r["n"] for r in pareto) or 1
    birikimli, kum = [], 0
    for r in pareto:
        kum += r["n"]
        birikimli.append(round(kum / toplam * 100, 1))

    yetenekler = []
    for k in conn.execute(
        "SELECT k.*, p.kod parca_kod FROM karakteristik k JOIN parca p ON p.id = k.parca_id WHERE k.kritik = 1 ORDER BY p.kod, k.no"
    ):
        alt, ust = kurallar.sinirlar(k)
        yetenekler.append((k, kurallar.yetenek(karakteristik_degerleri(conn, k["id"]), alt, ust)))

    son_ncr = conn.execute(
        "SELECT u.*, ie.no ie_no FROM uygunsuzluk u JOIN is_emri ie ON ie.id = u.is_emri_id "
        "WHERE u.durum='ACIK' ORDER BY u.id DESC LIMIT 5"
    ).fetchall()
    return render_template(
        "pano.html", sayilar=sayilar, acik_dof=acik_dof, ret_orani=ret_orani, muayene_sayisi=m["toplam"],
        pareto=pareto, birikimli=birikimli, yetenekler=yetenekler, son_ncr=son_ncr,
    )


# ---------- iş emirleri ----------

@bp.get("/is-emirleri")
def is_emirleri():
    durum = request.args.get("durum")
    sql = ("SELECT ie.*, p.kod parca_kod, p.ad parca_ad, "
           "(SELECT COUNT(*) FROM uygunsuzluk u WHERE u.is_emri_id = ie.id AND u.durum='ACIK') acik "
           "FROM is_emri ie JOIN parca p ON p.id = ie.parca_id")
    args = ()
    if durum in DURUM_ADI:
        sql += " WHERE ie.durum = ?"
        args = (durum,)
    rows = db().execute(sql + " ORDER BY ie.id DESC", args).fetchall()
    return render_template("is_emirleri.html", rows=rows, secili=durum)


@bp.post("/is-emirleri/ice-aktar")
def ice_aktar():
    f = request.files.get("dosya")
    if not f or not f.filename:
        flash("Dosya seçilmedi.", "hata")
        return redirect(url_for("web.is_emirleri"))
    try:
        sonuc = is_emirlerini_al(db(), dosya_oku(f.filename, f.read()), kaynak="ERP dosya")
    except Exception as e:  # bozuk dosya
        flash(f"Dosya okunamadı: {e}", "hata")
        return redirect(url_for("web.is_emirleri"))
    flash(f"{len(sonuc['eklenen'])} iş emri alındı.", "tamam")
    for no, sebep in sonuc["atlanan"]:
        flash(f"Atlandı {no}: {sebep}", "uyari")
    return redirect(url_for("web.is_emirleri"))


def is_emri_detay(conn, no):
    ie = conn.execute(
        "SELECT ie.*, p.kod parca_kod, p.ad parca_ad, p.revizyon, p.malzeme FROM is_emri ie "
        "JOIN parca p ON p.id = ie.parca_id WHERE ie.no = ?", (no,)
    ).fetchone()
    if ie is None:
        raise KuralHatasi(f"İş emri bulunamadı: {no}")
    return ie


@bp.get("/is-emri/<no>")
def is_emri(no):
    conn = db()
    try:
        ie = is_emri_detay(conn, no)
    except KuralHatasi as e:
        return render_template("hata.html", mesaj=str(e)), 404
    karakteristikler = conn.execute("SELECT * FROM karakteristik WHERE parca_id = ? ORDER BY no", (ie["parca_id"],)).fetchall()
    muayeneler = []
    for m in conn.execute("SELECT * FROM muayene WHERE is_emri_id = ? ORDER BY id", (ie["id"],)):
        olcumler = {o["karakteristik_id"]: o for o in conn.execute(
            "SELECT o.*, a.kod alet_kod FROM olcum o JOIN alet a ON a.id = o.alet_id WHERE o.muayene_id = ?", (m["id"],)
        )}
        muayeneler.append((m, olcumler))
    ncr = conn.execute("SELECT * FROM uygunsuzluk WHERE is_emri_id = ? ORDER BY id", (ie["id"],)).fetchall()
    return render_template(
        "is_emri.html", ie=ie, karakteristikler=karakteristikler, muayeneler=muayeneler, ncr=ncr,
        ozet=kurallar.kalite_ozeti(conn, no),
    )


@bp.route("/is-emri/<no>/muayene/<tur>", methods=["GET", "POST"])
def muayene(no, tur):
    conn = db()
    try:
        ie = is_emri_detay(conn, no)
    except KuralHatasi as e:
        return render_template("hata.html", mesaj=str(e)), 404
    karakteristikler = conn.execute("SELECT * FROM karakteristik WHERE parca_id = ? ORDER BY no", (ie["parca_id"],)).fetchall()
    aletler = {}
    for a in conn.execute("SELECT * FROM alet ORDER BY kod"):
        aletler.setdefault(a["tip"], []).append(a)

    hata = None
    if request.method == "POST":
        olcumler = [
            {"karakteristik_id": k["id"], "deger": request.form.get(f"deger_{k['id']}", ""),
             "alet_id": request.form.get(f"alet_{k['id']}") or 0}
            for k in karakteristikler
        ]
        try:
            kurallar.muayene_kaydet(conn, no, tur, request.form.get("personel", ""), olcumler)
            flash(f"{TUR_ADI.get(tur, tur)} muayenesi kaydedildi.", "tamam")
            return redirect(url_for("web.is_emri", no=no))
        except KuralHatasi as e:
            conn.rollback()
            hata = str(e)
    return render_template("muayene.html", ie=ie, tur=tur, karakteristikler=karakteristikler,
                           aletler=aletler, hata=hata, form=request.form)


# ---------- uygunsuzluk / DÖF ----------

@bp.get("/uygunsuzluklar")
def uygunsuzluklar():
    rows = db().execute(
        "SELECT u.*, ie.no ie_no, ie.lot FROM uygunsuzluk u JOIN is_emri ie ON ie.id = u.is_emri_id "
        "ORDER BY u.durum = 'KAPALI', u.id DESC"
    ).fetchall()
    return render_template("uygunsuzluklar.html", rows=rows)


@bp.route("/uygunsuzluk/<int:nid>", methods=["GET", "POST"])
def uygunsuzluk(nid):
    conn = db()
    hata = None
    if request.method == "POST":
        f = request.form
        try:
            kurallar.dof_kapat(conn, nid, f.get("kok_neden"), f.get("aksiyon"), f.get("sorumlu"),
                               f.get("karar"), f.get("hurda_adet") or 0)
            flash("DÖF kapatıldı.", "tamam")
            return redirect(url_for("web.uygunsuzluk", nid=nid))
        except (KuralHatasi, ValueError) as e:
            conn.rollback()
            hata = str(e)
    u = conn.execute(
        "SELECT u.*, ie.no ie_no, ie.lot, ie.adet, ie.hurda_adet ie_hurda, m.personel, m.tur, a.kod alet_kod "
        "FROM uygunsuzluk u JOIN is_emri ie ON ie.id = u.is_emri_id JOIN olcum o ON o.id = u.olcum_id "
        "JOIN muayene m ON m.id = o.muayene_id JOIN alet a ON a.id = o.alet_id WHERE u.id = ?", (nid,)
    ).fetchone()
    if u is None:
        return render_template("hata.html", mesaj="Uygunsuzluk kaydı bulunamadı."), 404
    return render_template("uygunsuzluk.html", u=u, hata=hata, form=request.form)


# ---------- ana veriler ----------

@bp.get("/parcalar")
def parcalar():
    conn = db()
    rows = []
    for p in conn.execute("SELECT * FROM parca ORDER BY kod"):
        rows.append((p, conn.execute("SELECT * FROM karakteristik WHERE parca_id = ? ORDER BY no", (p["id"],)).fetchall()))
    return render_template("parcalar.html", rows=rows)


@bp.get("/aletler")
def aletler():
    rows = db().execute(
        "SELECT a.*, (SELECT COUNT(*) FROM olcum o WHERE o.alet_id = a.id) kullanim FROM alet a ORDER BY kalibrasyon_bitis"
    ).fetchall()
    return render_template("aletler.html", rows=rows)


@bp.get("/spc/<int:kid>")
def spc(kid):
    conn = db()
    k = conn.execute(
        "SELECT k.*, p.kod parca_kod, p.ad parca_ad FROM karakteristik k JOIN parca p ON p.id = k.parca_id WHERE k.id = ?", (kid,)
    ).fetchone()
    if k is None:
        return render_template("hata.html", mesaj="Karakteristik bulunamadı."), 404
    rows = conn.execute(
        "SELECT o.deger, o.uygun, m.tarih, ie.no ie_no, ie.lot FROM olcum o JOIN muayene m ON m.id = o.muayene_id "
        "JOIN is_emri ie ON ie.id = m.is_emri_id WHERE o.karakteristik_id = ? ORDER BY m.tarih, o.id", (kid,)
    ).fetchall()
    alt, ust = kurallar.sinirlar(k)
    y = kurallar.yetenek([r["deger"] for r in rows], alt, ust)
    return render_template("spc.html", k=k, rows=rows, alt=alt, ust=ust, y=y)


@bp.get("/izlenebilirlik")
def izlenebilirlik():
    q = request.args.get("q", "").strip()
    sonuc = []
    if q:
        conn = db()
        for ie in conn.execute(
            "SELECT ie.*, p.kod parca_kod, p.ad parca_ad, p.revizyon FROM is_emri ie JOIN parca p ON p.id = ie.parca_id "
            "WHERE ie.lot LIKE ? OR ie.no LIKE ? ORDER BY ie.id", (f"%{q}%", f"%{q}%")
        ):
            olcumler = conn.execute(
                "SELECT m.tur, m.numune_no, m.personel, m.tarih, k.no kno, k.ad kad, o.deger, o.uygun, a.kod alet_kod, "
                "a.kalibrasyon_bitis FROM olcum o JOIN muayene m ON m.id = o.muayene_id "
                "JOIN karakteristik k ON k.id = o.karakteristik_id JOIN alet a ON a.id = o.alet_id "
                "WHERE m.is_emri_id = ? ORDER BY m.id, k.no", (ie["id"],)
            ).fetchall()
            sonuc.append((ie, olcumler))
    return render_template("izlenebilirlik.html", q=q, sonuc=sonuc)


# ---------- ERP API ----------

@bp.post("/api/is-emirleri")
def api_is_emri_al():
    veri = request.get_json(silent=True)
    if isinstance(veri, dict):
        veri = [veri]
    if not isinstance(veri, list) or not all(isinstance(v, dict) for v in veri):
        return jsonify({"hata": "JSON nesne ya da nesne listesi bekleniyor"}), 400
    sonuc = is_emirlerini_al(db(), veri, kaynak="ERP API")
    return jsonify({"eklenen": sonuc["eklenen"], "atlanan": [{"is_emri_no": n, "sebep": s} for n, s in sonuc["atlanan"]]}), (
        201 if sonuc["eklenen"] else 200
    )


@bp.get("/api/is-emirleri/<no>/kalite")
def api_kalite(no):
    try:
        return jsonify(kurallar.kalite_ozeti(db(), no))
    except KuralHatasi as e:
        return jsonify({"hata": str(e)}), 404


@bp.get("/api/kalite-durumlari")
def api_kalite_durumlari():
    conn = db()
    nolar = [r[0] for r in conn.execute("SELECT no FROM is_emri ORDER BY id")]
    return jsonify([kurallar.kalite_ozeti(conn, n) for n in nolar])
