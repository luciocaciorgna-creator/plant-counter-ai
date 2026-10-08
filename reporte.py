"""Informe en PDF de un lote: resumen, promedio y una página por muestra con la foto procesada."""
import io
import math
from datetime import datetime, timedelta, timezone

import cv2
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

VERDE, AMARILLO, ROJO, GRIS = (colors.HexColor(c) for c in ("#c8e6c9", "#fff0a8", "#f6bcbc", "#eceff1"))
OSCURO = colors.HexColor("#1b5e20")


def _t(x):
    """Texto seguro para la fuente estándar (solo Latin-1: tildes y ñ sí, emojis no)."""
    return str(x).encode("latin-1", "replace").decode("latin-1")


def _nan(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def _fmt(v, dec=1, miles=False):
    if _nan(v):
        return "-"
    return f"{v:,.{dec}f}".replace(",", ".") if miles and dec == 0 else (f"{v:,.{dec}f}" if miles else f"{v:.{dec}f}")


def _color(valor, verde, amarillo):
    if _nan(valor):
        return None
    return VERDE if valor <= verde else (AMARILLO if valor <= amarillo else ROJO)


def _jpg(img_bgr, ancho_max=1100):
    h, w = img_bgr.shape[:2]
    if w > ancho_max:
        img_bgr = cv2.resize(img_bgr, (ancho_max, int(h * ancho_max / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return buf.tobytes(), img_bgr.shape[1], img_bgr.shape[0]


def _imagen(img_bgr, max_w, max_h):
    datos, w, h = _jpg(img_bgr)
    k = min(max_w / w, max_h / h)
    return Image(io.BytesIO(datos), width=w * k, height=h * k)


def _tabla(filas, anchos, header=True, estilos=(), fs=8.5):
    t = Table(filas, colWidths=anchos, repeatRows=1 if header else 0)
    base = [("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), fs),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0bec5")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        base += [("BACKGROUND", (0, 0), (-1, 0), OSCURO), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(base + list(estilos)))
    return t


def _kpis(items, W, n=5, destacar=False):
    """items: lista de (titulo, valor, color_o_None). Arma tablas de n columnas, con el valor debajo del titulo."""
    out = []
    for i in range(0, len(items), n):
        grupo = items[i:i + n]
        est = [("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold")]
        if destacar:
            est += [("FONTSIZE", (0, 1), (-1, 1), 12), ("TOPPADDING", (0, 1), (-1, 1), 7),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 7)]
        for j, (_, _, col) in enumerate(grupo):
            if col:
                est.append(("BACKGROUND", (j, 1), (j, 1), col))
        out += [_tabla([[g[0] for g in grupo], [_t(g[1]) for g in grupo]], [W / n] * len(grupo), estilos=est),
                Spacer(1, 4)]
    return out


def _txt(v):
    return "-" if v is None or v == "" or _nan(v) else _t(v)


def _num(dec=1, miles=False):
    return lambda v: _fmt(v, dec, miles)


def _ent(v):
    return "-" if v is None or _nan(v) else str(int(v))


def _pct(v):
    return "-" if _nan(v) else f"{v:+.1f} %"


def _tabla_cols(cols, filas, W, ultima=None, fs=8):
    """cols: dicts con h (titulo), k (clave), f (formato), w (peso), sem (verde, amarillo, usar_abs) opcional."""
    todas = list(filas) + ([ultima] if ultima else [])
    datos = [[c["h"] for c in cols]]
    est = [("ALIGN", (0, 0), (0, -1), "LEFT")]
    for j, r in enumerate(todas, 1):
        datos.append([c["f"](r.get(c["k"])) for c in cols])
        for ci, c in enumerate(cols):
            if c.get("sem"):
                v = r.get(c["k"])
                if not _nan(v) and not isinstance(v, str):
                    col = _color(abs(v) if c["sem"][2] else v, c["sem"][0], c["sem"][1])
                    if col:
                        est.append(("BACKGROUND", (ci, j), (ci, j), col))
    if ultima:
        u = len(datos) - 1
        est += [("BACKGROUND", (0, u), (0, u), GRIS), ("FONTNAME", (0, u), (-1, u), "Helvetica-Bold")]
    tot = sum(c["w"] for c in cols)
    return _tabla(datos, [W * c["w"] / tot for c in cols], estilos=est, fs=fs)


def generar_pdf(est, lote, params, filas, prom, muestras, incluir_original=False, por_ambiente=None):
    """Devuelve los bytes del PDF.

    params:   entre_surcos, n_surcos, objetivo, largo_real, hibrido, siembra (texto o None), semillas
    filas:    una por muestra: nombre, plantas, metros, pl_m, pl_ha, media, desvio, cv, tam, emerg,
              ambiente, dds, estadio
    prom:     los mismos campos promediados (+ ent_sd, ent_cv)
    muestras: nombre, fecha, tot, surcos, proc (BGR), orig (BGR), sens, ambiente, dds, estadio, fmu, emerg
    por_ambiente: opcional, una fila por ambiente y la ultima con el general del lote
    """
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=20, textColor=OSCURO,
                        alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=13, textColor=OSCURO,
                        spaceBefore=8, spaceAfter=4)
    nrm = ParagraphStyle("n", parent=ss["BodyText"], fontName="Helvetica", fontSize=9, leading=12)
    peq = ParagraphStyle("p", parent=nrm, fontSize=7.5, leading=10, textColor=colors.HexColor("#546e7a"))

    ahora = datetime.now(timezone.utc) - timedelta(hours=3)  # Buenos Aires
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.5 * cm,
                            bottomMargin=1.6 * cm, title=_t(f"Stand de plantas - {est} - {lote}"),
                            author="Plant Counter AI")
    W = A4[0] - 3.2 * cm
    obj = params.get("objetivo", 0) or 0
    S = []

    # ------------------------------------------------------------------ portada / resumen
    sie = [f"Híbrido: {params['hibrido']}" if params.get("hibrido") else None,
           f"Siembra: {params['siembra']}" if params.get("siembra") else None,
           f"Semillas sembradas: {params['semillas']:,} /ha".replace(",", ".") if params.get("semillas") else None]
    sie = [x for x in sie if x]
    S += [Paragraph("Stand de plantas", h1),
          Paragraph(_t(f"<b>{est}</b> &nbsp;/&nbsp; <b>{lote}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
                       f"Informe del {ahora.strftime('%d/%m/%Y %H:%M')}"), nrm),
          Paragraph(_t(f"Distancia entre surcos: {params['entre_surcos']:g} cm &nbsp;|&nbsp; "
                       f"Surcos por foto: {params['n_surcos']} &nbsp;|&nbsp; "
                       + (f"Objetivo: {obj:,} pl/ha".replace(",", ".") if obj else "Sin densidad objetivo")
                       + (f" &nbsp;|&nbsp; Largo real de la foto: {params['largo_real']} cm"
                          if params.get("largo_real") else "")), nrm)]
    if sie:
        S.append(Paragraph(_t(" &nbsp;|&nbsp; ".join(sie)), nrm))
    S += [Spacer(1, 6), Paragraph("Resultado del lote (promedio de las muestras)", h2)]

    S += _kpis([("Densidad", _fmt(prom["pl_ha"], 0, True) + " pl/ha", None),
                ("Densidad", _fmt(prom["pl_m"], 2) + " pl/m", None),
                ("Media entre plantas", _fmt(prom["media"]) + " cm", None),
                ("Desvío", _fmt(prom["desvio"]) + " cm", None),
                ("CV", _fmt(prom["cv"]) + " %", _color(prom["cv"], 22, 30))], W, destacar=True)
    dds_v = [f["dds"] for f in filas if f.get("dds") is not None and not _nan(f["dds"])]
    k2 = [("Muestras", str(len(filas)), None), ("Metros de surco", _fmt(prom["metros"]) + " m", None),
          ("Plantas contadas", str(prom["plantas"]), None)]
    if not _nan(prom.get("tam")):
        k2.append(("Variación de tamaño", _fmt(prom["tam"]) + " %", _color(prom["tam"], 15, 50)))
    if not _nan(prom.get("emerg")):
        k2.append(("Emergencia", _fmt(prom["emerg"]) + " %", None))
    if dds_v:
        k2.append(("Días desde siembra", str(int(min(dds_v))) if min(dds_v) == max(dds_v)
                   else f"{int(min(dds_v))} a {int(max(dds_v))}", None))
    if obj:
        dev = (prom["pl_ha"] - obj) / obj * 100
        k2 += [("Desviación poblacional", f"{dev:+.1f} %", _color(abs(dev), 5, 10)),
               ("Coef. de logro", f"{prom['pl_ha'] / obj * 100:.1f} %", None)]
    S += _kpis(k2, W, n=4)
    if not _nan(prom.get("ent_sd")):
        S.append(Paragraph(_t(f"Variación de la densidad entre muestras: desvío {prom['ent_sd']:,.0f} pl/ha "
                              f"(CV {prom['ent_cv']:.1f} %).".replace(",", ".")), peq))
    if prom["metros"] < 10:
        S.append(Paragraph("Se midieron menos de 10 m de surco: el promedio es poco representativo "
                           "(se recomiendan cerca de 10 m por punto de muestreo).", peq))

    hay_tam = not _nan(prom.get("tam"))
    hay_em = not _nan(prom.get("emerg"))
    if por_ambiente:
        S.append(Paragraph("Promedio por ambiente", h2))
        ca = [dict(h="Ambiente", k="nombre", f=_txt, w=2.9), dict(h="Muestras", k="n", f=_ent, w=1.2),
              dict(h="Plantas", k="plantas", f=_ent, w=1.2), dict(h="m surco", k="metros", f=_num(1), w=1.1),
              dict(h="pl/m", k="pl_m", f=_num(2), w=1), dict(h="pl/ha", k="pl_ha", f=_num(0, True), w=1.3),
              dict(h="Media cm", k="media", f=_num(1), w=1.2), dict(h="Desvío cm", k="desvio", f=_num(1), w=1.2),
              dict(h="CV %", k="cv", f=_num(1), w=1, sem=(22, 30, False))]
        if hay_tam:
            ca.append(dict(h="Tam. %", k="tam", f=_num(1), w=1, sem=(15, 50, False)))
        if hay_em:
            ca.append(dict(h="Emerg. %", k="emerg", f=_num(1), w=1.1))
        if obj:
            ca.append(dict(h="Desv. pobl.", k="dev", f=_pct, w=1.3, sem=(5, 10, True)))
        S.append(_tabla_cols(ca, por_ambiente[:-1], W, ultima=por_ambiente[-1], fs=7.5 if len(ca) > 10 else 8.5))
        S.append(Spacer(1, 3))
        S.append(Paragraph("Cada ambiente es el promedio simple de sus muestras; el general del lote es el promedio "
                           "simple de todas las muestras.", peq))

    S.append(Paragraph("Detalle por muestra", h2))
    con_amb = any(f.get("ambiente") for f in filas)
    con_dds = any(f.get("dds") is not None and not _nan(f["dds"]) for f in filas)
    con_est = any(f.get("estadio") for f in filas)
    for i, f in enumerate(filas, 1):
        f["_lbl"] = f"{i}. {f['nombre']}"[:30]
    cd = [dict(h="Muestra", k="_lbl", f=_txt, w=2.6)]
    if con_amb:
        cd.append(dict(h="Ambiente", k="ambiente", f=_txt, w=1.5))
    if con_dds:
        cd.append(dict(h="DDS", k="dds", f=_ent, w=0.8))
    if con_est:
        cd.append(dict(h="Estadio", k="estadio", f=_txt, w=1))
    cd += [dict(h="Plantas", k="plantas", f=_ent, w=1), dict(h="m surco", k="metros", f=_num(1), w=1),
           dict(h="pl/m", k="pl_m", f=_num(2), w=0.9), dict(h="pl/ha", k="pl_ha", f=_num(0, True), w=1.3),
           dict(h="Media cm", k="media", f=_num(1), w=1.1), dict(h="Desvío cm", k="desvio", f=_num(1), w=1.1),
           dict(h="CV %", k="cv", f=_num(1), w=0.9, sem=(22, 30, False))]
    if hay_tam:
        cd.append(dict(h="Tam. %", k="tam", f=_num(1), w=1.1, sem=(15, 50, False)))
    if hay_em:
        cd.append(dict(h="Emerg. %", k="emerg", f=_num(1), w=1.3))
    fila_prom = {**prom, "_lbl": "PROMEDIO", "ambiente": "Todos", "dds": (sum(dds_v) / len(dds_v)) if dds_v else None,
                 "estadio": ""}
    S.append(_tabla_cols(cd, filas, W, ultima=fila_prom, fs=7.5 if len(cd) > 10 else 8.5))
    S.append(Spacer(1, 6))
    S.append(Paragraph("Semáforo del CV (variación entre plantas): verde hasta 22 %, amarillo hasta 30 %, rojo más. "
                       "Variación de tamaño (solo fotos): verde hasta 15 %, amarillo hasta 50 %, rojo más. "
                       "Desviación poblacional: verde hasta 5 %, amarillo hasta 10 %. "
                       "Emergencia = plantas logradas / semillas sembradas. DDS = días desde siembra. "
                       "Densidad = plantas por metro de surco / distancia entre surcos.", peq))

    # ------------------------------------------------------------------ una página por muestra
    for i, m in enumerate(muestras, 1):
        S.append(PageBreak())
        S.append(Paragraph(_t(f"Muestra {i}: {m['nombre']}" + (f" - {m['ambiente']}" if m.get("ambiente") else "")), h2))
        datos_m = [f"Muestreada el {m['fmu']}" if m.get("fmu") and m["fmu"] != "-" else None,
                   f"{int(m['dds'])} días desde siembra" if m.get("dds") is not None else None,
                   f"Estadio {m['estadio']}" if m.get("estadio") else None,
                   f"Cargada el {m['fecha']}" if m.get("fecha") else None]
        datos_m = [x for x in datos_m if x]
        if datos_m:
            S.append(Paragraph(_t(" | ".join(datos_m)), peq))
        t = m.get("tot")
        if t:
            S.append(Spacer(1, 3))
            S += _kpis([("Densidad", _fmt(t["pl_ha"], 0, True) + " pl/ha", None),
                        ("Densidad", _fmt(t["pl_m"], 2) + " pl/m", None),
                        ("Media", _fmt(t["media_cm"]) + " cm", None), ("Desvío", _fmt(t["desvio_cm"]) + " cm", None),
                        ("CV", _fmt(t["cv"]) + " %", _color(t["cv"], 22, 30)), ("Plantas", str(t["plantas"]), None)],
                       W, n=6)[:-1]
            k3 = []
            if not _nan(t.get("tam_cv")):
                k3.append(("Variación de tamaño", _fmt(t["tam_cv"]) + " %", _color(t["tam_cv"], 15, 50)))
            if m.get("emerg") is not None and not _nan(m["emerg"]):
                k3.append(("Emergencia", _fmt(m["emerg"]) + " %", None))
            if k3:
                S.append(Spacer(1, 3))
                S += _kpis(k3, W, n=6)[:-1]
        S.append(Spacer(1, 6))
        alto = 13.0 * cm
        if incluir_original:
            mitad = (W - 0.4 * cm) / 2
            fila = Table([[_imagen(m["proc"], mitad, alto), _imagen(m["orig"], mitad, alto)],
                          [Paragraph("Procesada", peq), Paragraph("Original", peq)]], colWidths=[mitad + 0.2 * cm] * 2)
            fila.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
            S.append(fila)
        else:
            im = _imagen(m["proc"], W, alto)
            im.hAlign = "CENTER"
            S.append(im)
        S.append(Spacer(1, 6))
        if t and m.get("surcos"):
            fs = [["Surco", "Plantas", "pl/m", "pl/ha", "Media (cm)", "Desvío (cm)", "CV (%)"]]
            es = []
            for j, s in enumerate(m["surcos"], 1):
                fs.append([str(s["surco"]), s["plantas"], _fmt(s["pl_m"], 2), _fmt(s["pl_ha"], 0, True),
                           _fmt(s["media_cm"]), _fmt(s["desvio_cm"]), _fmt(s["cv"])])
                cc = _color(s["cv"], 22, 30)
                if cc:
                    es.append(("BACKGROUND", (6, j), (6, j), cc))
            S.append(_tabla(fs, [W / 7] * 7, estilos=es))
            S.append(Spacer(1, 3))
            S.append(Paragraph(_t(
                f"Largo de surco en la foto: {t['largo_cm']:.0f} cm"
                + (" (cargado)" if params.get("largo_real") else " (estimado)")
                + f". Posibles dobles: {t['dobles']}. Baches: {t['baches']}. Sensibilidad: {m.get('sens', '-')}."), peq))
        elif not t:
            S.append(Paragraph("Menos de 2 plantas: no se pudo calcular esta muestra.", nrm))

    def pie(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#78909c"))
        canvas.drawString(1.6 * cm, 0.9 * cm, _t(f"Plant Counter AI - {est} / {lote}"))
        canvas.drawRightString(A4[0] - 1.6 * cm, 0.9 * cm, f"Página {doc_.page}")
        canvas.restoreState()

    doc.build(S, onFirstPage=pie, onLaterPages=pie)
    return buf.getvalue()
