"""Atölye ve kalite ekibinin kullandığı web arayüzü."""
import io
import json
import secrets
from datetime import date, timedelta

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from .. import denetim, dof, erp, fai_rapor, kullanicilar, muayene, olaylar, spc
from ..dof import KARARLAR
from ..ortak import KuralHatasi, bugun
from . import db
from .guvenlik import yetki
from .openapi import SPEC

bp = Blueprint("arayuz", __name__)

DURUM_ADI = {"FAI_BEKLIYOR": "İlk parça bekliyor", "URETIMDE": "Üretimde", "KARANTINA": "Karantina",
             "ONAYLI": "Sevke uygun"}
KARAR_ADI = {"YENIDEN_ISLEME": "Yeniden işleme", "SAPMA_KABUL": "Sapma ile kabul", "HURDA": "Hurda"}
TUR_ADI = {"FAI": "İlk parça (FAI)", "PROSES": "Proses", "FINAL": "Final"}
OLAY_DURUM_ADI = {"BEKLIYOR": "Bekliyor", "GONDERILDI": "Gönderildi", "HATA": "Hata · yeniden denenecek",
                  "VAZGECILDI": "Vazgeçildi · elle müdahale"}
ALARM_PENCERESI = 10   # son kaç ölçümdeki SPC ihlali panoda alarm sayılır
KALIBRASYON_UYARI_GUN = 30


@bp.app_context_processor
def sabitler():
    def nav_sayilari():
        conn = db()
        tek = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
        return {
            "karantina": tek("SELECT COUNT(*) FROM is_emri WHERE durum = 'KARANTINA'"),
            "acik_ncr": tek("SELECT COUNT(*) FROM uygunsuzluk WHERE durum = 'ACIK'"),
            "kalibrasyon": tek("SELECT COUNT(*) FROM alet WHERE kalibrasyon_bitis < ?", bugun()),
            "olay": tek("SELECT COUNT(*) FROM olay WHERE durum != 'GONDERILDI'"),
        }

    return {"DURUM_ADI": DURUM_ADI, "KARAR_ADI": KARAR_ADI, "TUR_ADI": TUR_ADI, "OLAY_DURUM_ADI": OLAY_DURUM_ADI,
            "OLAY_TURLERI": olaylar.TURLER, "bugun": bugun(), "nav_sayilari": nav_sayilari, "demo_turu": demo_turu}


def demo_turu():
    """Demo modunda ekranın üstündeki tur: projeyi ilk kez açan kişiye hikâyeyi sırayla gösterir.

    Hikâye son uygunsuzluk üzerinden kurulur (açık olan önce): karantinadaki lot, nedeni olan
    karakteristiğin SPC grafiği, DÖF kaydı. Demo dışı kurulumda tur gösterilmez.
    """
    if not current_app.config["DEMO_ERP"] or request.endpoint == "arayuz.giris":
        return None
    ncr = db().execute(
        "SELECT u.id, ie.no, o.karakteristik_id kid FROM uygunsuzluk u JOIN is_emri ie ON ie.id = u.is_emri_id "
        "JOIN olcum o ON o.id = u.olcum_id ORDER BY u.durum = 'ACIK' DESC, u.id DESC LIMIT 1"
    ).fetchone()
    adimlar = [
        ("Pano", "Lot akışı ve bugün dikkat isteyen işler tek ekranda.", url_for(".pano"), {"arayuz.pano"}),
        ("Karantinadaki lot", "Tolerans dışı ölçüm otomatik uygunsuzluk açtı; lot karantinada, ERP'ye bildirildi.",
         url_for(".is_emri", no=ncr["no"]) if ncr else url_for(".is_emirleri"), {"arayuz.is_emri", "arayuz.is_emirleri"}),
        ("SPC grafiği", "Sarı noktalar erken uyarı: takım aşınmasını parça tolerans dışına çıkmadan önce gösterdi.",
         url_for(".spc_grafik", kid=ncr["kid"]) if ncr else url_for(".spc_listesi"), {"arayuz.spc_grafik"}),
        ("DÖF", "Kök neden, faaliyet ve ürün kararı girilir; son DÖF kapanınca lot karantinadan çıkar.",
         url_for(".uygunsuzluk", nid=ncr["id"]) if ncr else url_for(".uygunsuzluklar"),
         {"arayuz.uygunsuzluk", "arayuz.uygunsuzluklar"}),
        ("ERP olayları", "Her kalite kararı kuyruktan ERP'ye gider. 'Bekleyenleri şimdi gönder' ile deneyin.",
         url_for(".entegrasyon"), {"arayuz.entegrasyon", "arayuz.api_belgesi"}),
    ]
    simdi_ = next((i for i, a in enumerate(adimlar) if request.endpoint in a[3]), None)
    return {"adimlar": adimlar, "simdi": simdi_}


@bp.app_template_filter("tol")
def tol(k):
    a, u = k["alt_sapma"], k["ust_sapma"]
    if a == -u:
        return f"{k['nominal']:g} ±{u:g}"
    isaretli = lambda x: "0" if x == 0 else f"{x:+g}"  # noqa: E731
    return f"{k['nominal']:g} {isaretli(u)} / {isaretli(a)}"


@bp.app_template_filter("konum")
def konum(deger, k):
    """Ölçümün tolerans bandındaki yeri, şablondaki tolerans cetveli için 0–100 aralığına kırpılmış yüzde."""
    return max(-6, min(106, muayene.tolerans_konumu(deger, k) * 100))


@bp.app_template_filter("ondalik")
def ondalik(x, basamak=2):
    return f"{x:.{basamak}f}".replace(".", ",")


# ---------- oturum ----------

@bp.route("/giris", methods=["GET", "POST"])
def giris():
    hata = None
    if request.method == "POST":
        k = kullanicilar.dogrula(db(), request.form.get("kullanici_adi"), request.form.get("parola"))
        if k:
            session.clear()  # oturum sabitlemeye karşı: girişte yeni oturum, yeni CSRF jetonu
            session["kid"] = k["id"]
            session["csrf"] = secrets.token_urlsafe(32)
            sonra = request.args.get("sonra", "")
            guvenli = sonra.startswith("/") and not sonra.startswith("//") and "\\" not in sonra
            return redirect(sonra if guvenli else url_for(".pano"))
        hata = "Kullanıcı adı ya da parola yanlış."
    kullanici_listesi = []
    if current_app.config["DEMO_ERP"]:  # demo kurulumunda hesapları göster; üretimde gösterilmez
        kullanici_listesi = db().execute("SELECT kullanici_adi, ad, rol FROM kullanici ORDER BY id").fetchall()
    return render_template("giris.html", hata=hata, kullanici_listesi=kullanici_listesi)


@bp.post("/cikis")
def cikis():
    session.clear()
    return redirect(url_for(".giris"))


# ---------- pano ----------

def karakteristik_serisi(conn, kid):
    return conn.execute(
        "SELECT o.deger, o.uygun, m.tarih, ie.no ie_no, ie.lot FROM olcum o JOIN muayene m ON m.id = o.muayene_id "
        "JOIN is_emri ie ON ie.id = m.is_emri_id WHERE o.karakteristik_id = ? ORDER BY m.tarih, o.id", (kid,)
    ).fetchall()


@bp.get("/")
def pano():
    conn = db()
    sayilar = {r["durum"]: r["n"] for r in conn.execute("SELECT durum, COUNT(*) n FROM is_emri GROUP BY durum")}
    acik_dof = conn.execute("SELECT COUNT(*) FROM uygunsuzluk WHERE durum='ACIK'").fetchone()[0]
    otuz_gun = (date.today() - timedelta(days=30)).isoformat()
    m = conn.execute("SELECT COUNT(*) toplam, SUM(sonuc='RED') red FROM muayene WHERE tarih >= ?", (otuz_gun,)).fetchone()
    ret_orani = (m["red"] or 0) / m["toplam"] * 100 if m["toplam"] else 0.0

    pareto = conn.execute(
        "SELECT p.kod || ' · ' || k.ad etiket, COUNT(*) n FROM uygunsuzluk u "
        "JOIN olcum o ON o.id = u.olcum_id JOIN karakteristik k ON k.id = o.karakteristik_id "
        "JOIN parca p ON p.id = k.parca_id GROUP BY k.id ORDER BY n DESC, etiket"
    ).fetchall()
    toplam, kum, birikimli = sum(r["n"] for r in pareto) or 1, 0, []
    for r in pareto:
        kum += r["n"]
        birikimli.append(round(kum / toplam * 100, 1))

    yetenekler, alarmlar = [], []
    for k in conn.execute("SELECT k.*, p.kod parca_kod FROM karakteristik k JOIN parca p ON p.id = k.parca_id "
                          "WHERE k.kritik = 1 ORDER BY p.kod, k.no"):
        degerler = [r["deger"] for r in karakteristik_serisi(conn, k["id"])]
        y = spc.yeterlilik(degerler, *muayene.sinirlar(k))
        yetenekler.append((k, y))
        son_ihlaller = [i for i in spc.kural_ihlalleri(degerler) if i["indeks"] >= len(degerler) - ALARM_PENCERESI]
        if son_ihlaller:
            alarmlar.append((k, son_ihlaller[-1], degerler[-1]))
    yetenekler.sort(key=lambda t: t[1]["cpk"] if t[1] else 99)

    sinir = (date.today() + timedelta(days=KALIBRASYON_UYARI_GUN)).isoformat()
    kalibrasyon = conn.execute("SELECT * FROM alet WHERE kalibrasyon_bitis <= ? ORDER BY kalibrasyon_bitis",
                               (sinir,)).fetchall()
    son_ncr = conn.execute(
        "SELECT u.*, ie.no ie_no FROM uygunsuzluk u JOIN is_emri ie ON ie.id = u.is_emri_id "
        "WHERE u.durum='ACIK' ORDER BY u.id DESC LIMIT 5").fetchall()
    bekleyen_olay = conn.execute("SELECT COUNT(*) FROM olay WHERE durum != 'GONDERILDI'").fetchone()[0]
    olay_hatalari = conn.execute("SELECT * FROM olay WHERE durum IN ('HATA', 'VAZGECILDI') ORDER BY id").fetchall()
    return render_template(
        "pano.html", sayilar=sayilar, acik_dof=acik_dof, ret_orani=ret_orani, muayene_sayisi=m["toplam"],
        pareto=pareto, birikimli=birikimli, yetenekler=yetenekler, alarmlar=alarmlar, kalibrasyon=kalibrasyon,
        son_ncr=son_ncr, bekleyen_olay=bekleyen_olay, olay_hatalari=olay_hatalari)


# ---------- iş emirleri ----------

@bp.get("/is-emirleri")
def is_emirleri():
    durum = request.args.get("durum")
    sql = ("SELECT ie.*, p.kod parca_kod, p.ad parca_ad, "
           "(SELECT COUNT(*) FROM uygunsuzluk u WHERE u.is_emri_id = ie.id AND u.durum='ACIK') acik "
           "FROM is_emri ie JOIN parca p ON p.id = ie.parca_id")
    args = ()
    if durum in DURUM_ADI:
        sql, args = sql + " WHERE ie.durum = ?", (durum,)
    rows = db().execute(sql + " ORDER BY ie.id DESC", args).fetchall()
    return render_template("is_emirleri.html", rows=rows, secili=durum)


@bp.post("/is-emirleri/ice-aktar")
@yetki("erp_ice_aktar")
def ice_aktar():
    f = request.files.get("dosya")
    if not f or not f.filename:
        flash("Dosya seçilmedi.", "hata")
        return redirect(url_for(".is_emirleri"))
    try:
        satirlar = erp.dosya_oku(f.filename, f.read())
    except Exception as e:  # bozuk ya da desteklenmeyen dosya: kullanıcıya göster
        flash(f"Dosya okunamadı: {e}", "hata")
        return redirect(url_for(".is_emirleri"))
    sonuc = erp.is_emirlerini_al(db(), satirlar, kaynak="ERP dosya", kullanici=g.kullanici["ad"])
    flash(f"{len(sonuc['eklenen'])} iş emri alındı.", "tamam")
    for no, sebep in sonuc["atlanan"]:
        flash(f"Atlandı {no}: {sebep}", "uyari")
    return redirect(url_for(".is_emirleri"))


def is_emri_detay(conn, no):
    ie = conn.execute(
        "SELECT ie.*, p.kod parca_kod, p.ad parca_ad, p.revizyon, p.malzeme FROM is_emri ie "
        "JOIN parca p ON p.id = ie.parca_id WHERE ie.no = ?", (no,)).fetchone()
    if ie is None:
        abort(404, f"İş emri bulunamadı: {no}")
    return ie


@bp.get("/is-emri/<no>")
def is_emri(no):
    conn = db()
    ie = is_emri_detay(conn, no)
    karakteristikler = conn.execute("SELECT * FROM karakteristik WHERE parca_id = ? ORDER BY no",
                                    (ie["parca_id"],)).fetchall()
    muayeneler = []
    for m in conn.execute("SELECT * FROM muayene WHERE is_emri_id = ? ORDER BY id", (ie["id"],)):
        olcumler = {o["karakteristik_id"]: o for o in conn.execute(
            "SELECT o.*, a.kod alet_kod FROM olcum o JOIN alet a ON a.id = o.alet_id WHERE o.muayene_id = ?",
            (m["id"],))}
        muayeneler.append((m, olcumler))
    ncr = conn.execute("SELECT * FROM uygunsuzluk WHERE is_emri_id = ? ORDER BY id", (ie["id"],)).fetchall()
    olay_listesi = conn.execute("SELECT * FROM olay WHERE is_emri_no = ? ORDER BY id", (no,)).fetchall()
    return render_template("is_emri.html", ie=ie, karakteristikler=karakteristikler, muayeneler=muayeneler,
                           ncr=ncr, ozet=erp.kalite_ozeti(conn, no), olay_listesi=olay_listesi)


@bp.get("/is-emri/<no>/fai.xlsx")
def fai_indir(no):
    try:
        icerik, ad = fai_rapor.olustur(db(), no)
    except KuralHatasi as e:
        flash(str(e), "hata")
        return redirect(url_for(".is_emri", no=no))
    return send_file(io.BytesIO(icerik), as_attachment=True, download_name=ad,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/is-emri/<no>/muayene/<tur>", methods=["GET", "POST"])
@yetki("muayene")
def muayene_formu(no, tur):
    if tur not in muayene.TURLER:
        abort(404)
    conn = db()
    ie = is_emri_detay(conn, no)
    karakteristikler = conn.execute("SELECT * FROM karakteristik WHERE parca_id = ? ORDER BY no",
                                    (ie["parca_id"],)).fetchall()
    aletler = {}
    for a in conn.execute("SELECT * FROM alet ORDER BY kod"):
        aletler.setdefault(a["tip"], []).append(a)

    hata = None
    if request.method == "POST":
        olcumler = [{"karakteristik_id": k["id"], "deger": request.form.get(f"deger_{k['id']}", ""),
                     "alet_id": request.form.get(f"alet_{k['id']}") or 0} for k in karakteristikler]
        try:
            muayene.muayene_kaydet(conn, no, tur, g.kullanici["ad"], olcumler)
            yeni = conn.execute("SELECT durum FROM is_emri WHERE no = ?", (no,)).fetchone()["durum"]
            if yeni == "KARANTINA":
                flash("Tolerans dışı ölçüm var: uygunsuzluk açıldı, lot karantinaya alındı ve ERP'ye bildirildi.",
                      "hata")
            else:
                flash(f"{TUR_ADI[tur]} muayenesi kaydedildi.", "tamam")
            return redirect(url_for(".is_emri", no=no))
        except KuralHatasi as e:
            hata = str(e)
    return render_template("muayene.html", ie=ie, tur=tur, karakteristikler=karakteristikler, aletler=aletler,
                           hata=hata, form=request.form)


# ---------- uygunsuzluk / DÖF ----------

@bp.get("/uygunsuzluklar")
def uygunsuzluklar():
    rows = db().execute(
        "SELECT u.*, ie.no ie_no, ie.lot FROM uygunsuzluk u JOIN is_emri ie ON ie.id = u.is_emri_id "
        "ORDER BY u.durum = 'KAPALI', u.id DESC").fetchall()
    return render_template("uygunsuzluklar.html", rows=rows)


@bp.route("/uygunsuzluk/<int:nid>", methods=["GET", "POST"])
def uygunsuzluk(nid):
    conn = db()
    hata = None
    if request.method == "POST":
        if not kullanicilar.yetkili_mi(g.kullanici["rol"], "dof"):
            abort(403)
        f = request.form
        try:
            dof.dof_kapat(conn, nid, f.get("kok_neden"), f.get("aksiyon"), f.get("sorumlu"), f.get("karar"),
                          f.get("hurda_adet") or 0, kapatan=g.kullanici["ad"])
            flash("DÖF kapatıldı; ERP'ye bildirim kuyruğa alındı.", "tamam")
            return redirect(url_for(".uygunsuzluk", nid=nid))
        except KuralHatasi as e:
            hata = str(e)
    u = conn.execute(
        "SELECT u.*, ie.no ie_no, ie.lot, ie.adet, ie.hurda_adet ie_hurda, m.personel, m.tur, a.kod alet_kod, "
        "k.id kid, k.ad kad FROM uygunsuzluk u JOIN is_emri ie ON ie.id = u.is_emri_id "
        "JOIN olcum o ON o.id = u.olcum_id JOIN muayene m ON m.id = o.muayene_id JOIN alet a ON a.id = o.alet_id "
        "JOIN karakteristik k ON k.id = o.karakteristik_id WHERE u.id = ?", (nid,)).fetchone()
    if u is None:
        abort(404, "Uygunsuzluk kaydı bulunamadı.")
    gecmis = conn.execute(
        "SELECT kok_neden, aksiyon, karar, kapanis FROM uygunsuzluk u2 JOIN olcum o ON o.id = u2.olcum_id "
        "WHERE o.karakteristik_id = ? AND u2.durum = 'KAPALI' AND u2.id != ? ORDER BY u2.id DESC LIMIT 3",
        (u["kid"], nid)).fetchall()
    return render_template("uygunsuzluk.html", u=u, hata=hata, form=request.form, gecmis=gecmis, KARARLAR=KARARLAR)


# ---------- ana veri ----------

@bp.get("/parcalar")
def parcalar():
    conn = db()
    rows = [(p, conn.execute("SELECT * FROM karakteristik WHERE parca_id = ? ORDER BY no", (p["id"],)).fetchall())
            for p in conn.execute("SELECT * FROM parca ORDER BY kod")]
    return render_template("parcalar.html", rows=rows)


@bp.get("/aletler")
def aletler():
    rows = db().execute("SELECT a.*, (SELECT COUNT(*) FROM olcum o WHERE o.alet_id = a.id) kullanim FROM alet a "
                        "ORDER BY kalibrasyon_bitis").fetchall()
    uyari = (date.today() + timedelta(days=KALIBRASYON_UYARI_GUN)).isoformat()
    return render_template("aletler.html", rows=rows, uyari=uyari)


@bp.post("/aletler/<int:aid>/kalibrasyon")
@yetki("kalibrasyon")
def kalibrasyon_yenile(aid):
    yeni = request.form.get("bitis", "")
    try:
        date.fromisoformat(yeni)
    except ValueError:
        flash("Geçerli bir tarih girilmeli.", "hata")
        return redirect(url_for(".aletler"))
    if yeni < bugun():
        flash("Yeni kalibrasyon bitişi bugünden önce olamaz.", "hata")
        return redirect(url_for(".aletler"))
    conn = db()
    alet = conn.execute("SELECT * FROM alet WHERE id = ?", (aid,)).fetchone()
    if alet is None:
        abort(404)
    with conn:
        conn.execute("UPDATE alet SET kalibrasyon_bitis = ? WHERE id = ?", (yeni, aid))
        denetim.kaydet(conn, g.kullanici["ad"], "KALIBRASYON_YENILENDI", "alet", alet["kod"],
                       {"eski": alet["kalibrasyon_bitis"], "yeni": yeni})
    flash(f"{alet['kod']} kalibrasyonu {yeni} tarihine uzatıldı.", "tamam")
    return redirect(url_for(".aletler"))


# ---------- analiz ----------

@bp.get("/spc")
def spc_listesi():
    k = db().execute("SELECT id FROM karakteristik WHERE kritik = 1 ORDER BY id LIMIT 1").fetchone()
    return redirect(url_for(".spc_grafik", kid=k["id"])) if k else redirect(url_for(".parcalar"))


@bp.get("/spc/<int:kid>")
def spc_grafik(kid):
    conn = db()
    k = conn.execute("SELECT k.*, p.kod parca_kod, p.ad parca_ad FROM karakteristik k "
                     "JOIN parca p ON p.id = k.parca_id WHERE k.id = ?", (kid,)).fetchone()
    if k is None:
        abort(404, "Karakteristik bulunamadı.")
    rows = karakteristik_serisi(conn, kid)
    degerler = [r["deger"] for r in rows]
    alt, ust = muayene.sinirlar(k)
    sinir = spc.imr(degerler)
    y = spc.yeterlilik(degerler, alt, ust)
    ihlaller = spc.kural_ihlalleri(degerler, sinir)
    tum = conn.execute("SELECT k.id, k.ad, p.kod FROM karakteristik k JOIN parca p ON p.id = k.parca_id "
                       "WHERE k.kritik = 1 ORDER BY p.kod, k.no").fetchall()
    return render_template("spc.html", k=k, rows=rows, alt=alt, ust=ust, sinir=sinir, y=y, ihlaller=ihlaller, tum=tum)


@bp.get("/izlenebilirlik")
def izlenebilirlik():
    q = request.args.get("q", "").strip()
    sonuc = []
    if q:
        conn = db()
        for ie in conn.execute(
            "SELECT ie.*, p.kod parca_kod, p.ad parca_ad, p.revizyon FROM is_emri ie JOIN parca p ON p.id = ie.parca_id "
            "WHERE ie.lot LIKE ? OR ie.no LIKE ? ORDER BY ie.id LIMIT 20", (f"%{q}%", f"%{q}%")):
            olcumler = conn.execute(
                "SELECT m.tur, m.numune_no, m.personel, m.tarih, k.no kno, k.ad kad, o.deger, o.uygun, a.kod alet_kod, "
                "a.kalibrasyon_bitis FROM olcum o JOIN muayene m ON m.id = o.muayene_id "
                "JOIN karakteristik k ON k.id = o.karakteristik_id JOIN alet a ON a.id = o.alet_id "
                "WHERE m.is_emri_id = ? ORDER BY m.id, k.no", (ie["id"],)).fetchall()
            sonuc.append((ie, olcumler))
    return render_template("izlenebilirlik.html", q=q, sonuc=sonuc)


# ---------- entegrasyon ----------

def webhook_adresi():
    url = current_app.config["ERP_WEBHOOK"]
    if not url and current_app.config["DEMO_ERP"]:
        url = url_for("demo_erp.webhook", _external=True)
    return url


@bp.get("/entegrasyon")
def entegrasyon():
    conn = db()
    olay_listesi = conn.execute("SELECT * FROM olay ORDER BY id DESC LIMIT 60").fetchall()
    sayim = {r["durum"]: r["n"] for r in conn.execute("SELECT durum, COUNT(*) n FROM olay GROUP BY durum")}
    erp_kutusu = []
    if current_app.config["DEMO_ERP"]:
        erp_kutusu = [dict(r) | {"veri": json.loads(r["veri"])} for r in
                      conn.execute("SELECT * FROM demo_erp_kutusu ORDER BY id DESC LIMIT 12")]
    return render_template("entegrasyon.html", olay_listesi=olay_listesi, sayim=sayim, erp_kutusu=erp_kutusu,
                           webhook=webhook_adresi(), spec=SPEC)


@bp.post("/entegrasyon/gonder")
@yetki("entegrasyon")
def olaylari_gonder():
    url = webhook_adresi()
    if not url:
        flash("ERP webhook adresi tanımlı değil (KALITEHAT_ERP_WEBHOOK).", "hata")
        return redirect(url_for(".entegrasyon"))
    s = olaylar.gonder_bekleyenler(db(), url, api_anahtari=current_app.config["API_ANAHTARI"])
    flash(f"{s['gonderilen']} olay ERP'ye iletildi, {s['hatali']} olay hata verdi (yeniden denenecek).",
          "tamam" if not s["hatali"] else "uyari")
    return redirect(url_for(".entegrasyon"))


@bp.post("/entegrasyon/olay/<int:oid>/yeniden")
@yetki("entegrasyon")
def olay_yeniden(oid):
    olaylar.yeniden_kuyruga_al(db(), oid)
    flash(f"Olay #{oid} yeniden kuyruğa alındı.", "tamam")
    return redirect(url_for(".entegrasyon"))


@bp.get("/api-belgesi")
def api_belgesi():
    demo = current_app.config["API_ANAHTARI"] == "demo-api-anahtari"
    return render_template("api_belgesi.html", spec=SPEC, api_anahtari_demo=demo,
                           ornek_anahtar="demo-api-anahtari" if demo else "<API-ANAHTARI>")


@bp.get("/denetim")
def denetim_izi():
    rows = db().execute("SELECT * FROM denetim ORDER BY id DESC LIMIT 200").fetchall()
    return render_template("denetim.html", rows=[dict(r) | {"ayrinti": json.loads(r["ayrinti"]) if r["ayrinti"]
                                                            else None} for r in rows])


@bp.app_errorhandler(404)
def bulunamadi(e):
    return render_template("hata.html", baslik="Bulunamadı", mesaj=getattr(e, "description", "")), 404


@bp.app_errorhandler(403)
def yasak(_):
    return render_template("hata.html", baslik="Yetki yok", mesaj="Bu işlem için rolünüz yetmiyor."), 403


@bp.app_errorhandler(400)
def gecersiz(e):
    return render_template("hata.html", baslik="Geçersiz istek", mesaj=getattr(e, "description", "")), 400
