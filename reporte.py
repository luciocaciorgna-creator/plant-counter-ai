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


def _tabla(filas, anchos, header=True, estilos=()):
    t = Table(filas, colWidths=anchos, repeatRows=1 if header else 0)
    base = [("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0bec5")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        base += [("BACKGROUND", (0, 0), (-1, 0), OSCURO), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(base + list(estilos)))
    return t


def generar_pdf(est, lote, params, filas, prom, muestras, incluir_original=False, por_ambiente=None):
    """Devuelve los bytes del PDF.

    params:   dict con entre_surcos, n_surcos, objetivo, largo_real
    filas:    lista de dicts (una por muestra) con nombre, plantas, metros, pl_m, pl_ha, media, desvio, cv
    prom:     dict con los mismos campos promediados (+ ent_sd, ent_cv)
    muestras: lista de dicts con nombre, fecha, tot, surcos, proc (BGR), orig (BGR), sens, ambiente
    por_ambiente: opcional, lista de dicts (nombre, n, plantas, metros, pl_m, pl_ha, media, desvio, cv, dev)
              con una fila por ambiente y la última con el general del lote
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
    S += [Paragraph("Stand de plantas", h1),
          Paragraph(_t(f"<b>{est}</b> &nbsp;/&nbsp; <b>{lote}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
                       f"Informe del {ahora.strftime('%d/%m/%Y %H:%M')}"), nrm),
          Paragraph(_t(f"Distancia entre surcos: {params['entre_surcos']:g} cm &nbsp;|&nbsp; "
                       f"Surcos por foto: {params['n_surcos']} &nbsp;|&nbsp; "
                       + (f"Objetivo: {obj:,} pl/ha".replace(",", ".") if obj else "Sin densidad objetivo")
                       + (f" &nbsp;|&nbsp; Largo real de la foto: {params['largo_real']} cm"
                          if params.get("largo_real") else "")), nrm),
          Spacer(1, 6), Paragraph("Resultado del lote (promedio de las muestras)", h2)]

    kpi = [["Densidad", "Densidad", "Media entre plantas", "Desvío", "CV"],
           [_fmt(prom["pl_ha"], 0, True) + " pl/ha", _fmt(prom["pl_m"], 2) + " pl/m", _fmt(prom["media"]) + " cm",
            _fmt(prom["desvio"]) + " cm", _fmt(prom["cv"]) + " %"]]
    est_kpi = [("FONTSIZE", (0, 1), (-1, 1), 12), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
               ("TOPPADDING", (0, 1), (-1, 1), 7), ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
               ("ALIGN", (0, 0), (-1, -1), "CENTER")]
    c = _color(prom["cv"], 22, 30)
    if c:
        est_kpi.append(("BACKGROUND", (4, 1), (4, 1), c))
    S.append(_tabla(kpi, [W / 5] * 5, estilos=est_kpi))
    S.append(Spacer(1, 4))

    kpi2 = [["Muestras", "Metros de surco", "Plantas contadas"], [str(len(filas)), _fmt(prom["metros"]) + " m",
                                                                  str(prom["plantas"])]]
    anchos2 = [W / 5] * 3
    est2 = [("ALIGN", (0, 0), (-1, -1), "CENTER")]
    if obj:
        dev = (prom["pl_ha"] - obj) / obj * 100
        kpi2[0] += ["Desviación poblacional", "Coef. de logro"]
        kpi2[1] += [f"{dev:+.1f} %", f"{prom['pl_ha'] / obj * 100:.1f} %"]
        anchos2 = [W / 5] * 5
        cd = _color(abs(dev), 5, 10)
        if cd:
            est2.append(("BACKGROUND", (3, 1), (3, 1), cd))
    S.append(_tabla(kpi2, anchos2, estilos=est2))
    S.append(Spacer(1, 3))
    if not _nan(prom.get("ent_sd")):
        S.append(Paragraph(_t(f"Variación de la densidad entre muestras: desvío {prom['ent_sd']:,.0f} pl/ha "
                              f"(CV {prom['ent_cv']:.1f} %).".replace(",", ".")), peq))
    if prom["metros"] < 10:
        S.append(Paragraph("Se midieron menos de 10 m de surco: el promedio es poco representativo "
                           "(se recomiendan cerca de 10 m por punto de muestreo).", peq))

    if por_ambiente:
        S.append(Paragraph("Promedio por ambiente", h2))
        cab_a = ["Ambiente", "Muestras", "Plantas", "m surco", "pl/m", "pl/ha", "Media (cm)", "Desvío (cm)", "CV (%)"]
        if obj:
            cab_a.append("Desv. pobl.")
        da = [cab_a]
        ea = [("ALIGN", (0, 0), (0, -1), "LEFT")]
        for j, p in enumerate(por_ambiente, 1):
            fila_a = [_t(p["nombre"]), p["n"], p["plantas"], _fmt(p["metros"]), _fmt(p["pl_m"], 2),
                      _fmt(p["pl_ha"], 0, True), _fmt(p["media"]), _fmt(p["desvio"]), _fmt(p["cv"])]
            cc = _color(p["cv"], 22, 30)
            if cc:
                ea.append(("BACKGROUND", (8, j), (8, j), cc))
            if obj:
                fila_a.append("-" if p.get("dev") is None else f"{p['dev']:+.1f} %")
                if p.get("dev") is not None:
                    cd = _color(abs(p["dev"]), 5, 10)
                    if cd:
                        ea.append(("BACKGROUND", (9, j), (9, j), cd))
            da.append(fila_a)
        ult = len(da) - 1
        ea += [("BACKGROUND", (0, ult), (0, ult), GRIS), ("FONTNAME", (0, ult), (-1, ult), "Helvetica-Bold")]
        ncol = len(cab_a)
        S.append(_tabla(da, [W * 0.19] + [W * 0.81 / (ncol - 1)] * (ncol - 1), estilos=ea))
        S.append(Spacer(1, 3))
        S.append(Paragraph("Cada ambiente es el promedio simple de sus muestras; el general del lote es el promedio "
                           "simple de todas las muestras.", peq))

    S.append(Paragraph("Detalle por muestra", h2))
    con_amb = any(f.get("ambiente") for f in filas)
    cab = ["Muestra"] + (["Ambiente"] if con_amb else []) + ["Plantas", "m surco", "pl/m", "pl/ha", "Media (cm)",
                                                             "Desvío (cm)", "CV (%)"]
    ccv = len(cab) - 1
    datos = [cab]
    est_t = []
    for i, f in enumerate(filas, 1):
        datos.append([_t(f"{i}. {f['nombre']}")[:34]] + ([_t(f.get("ambiente") or "-")] if con_amb else [])
                     + [f["plantas"], _fmt(f["metros"]), _fmt(f["pl_m"], 2), _fmt(f["pl_ha"], 0, True),
                        _fmt(f["media"]), _fmt(f["desvio"]), _fmt(f["cv"])])
        cc = _color(f["cv"], 22, 30)
        if cc:
            est_t.append(("BACKGROUND", (ccv, i), (ccv, i), cc))
    n = len(datos)
    datos.append(["PROMEDIO"] + (["Todos"] if con_amb else [])
                 + [prom["plantas"], _fmt(prom["metros"]), _fmt(prom["pl_m"], 2), _fmt(prom["pl_ha"], 0, True),
                    _fmt(prom["media"]), _fmt(prom["desvio"]), _fmt(prom["cv"])])
    est_t += [("BACKGROUND", (0, n), (-1, n), GRIS), ("FONTNAME", (0, n), (-1, n), "Helvetica-Bold"),
              ("ALIGN", (0, 0), (0, -1), "LEFT")]
    cc = _color(prom["cv"], 22, 30)
    if cc:
        est_t.append(("BACKGROUND", (ccv, n), (ccv, n), cc))
    ncol = len(cab)
    anchos = ([W * 0.25, W * 0.13] + [W * 0.62 / 6] * 6) if con_amb else ([W * 0.28] + [W * 0.72 / 7] * 7)
    S.append(_tabla(datos, anchos, estilos=est_t))
    S.append(Spacer(1, 6))
    S.append(Paragraph("Semáforo del CV (variación entre plantas): verde hasta 22 %, amarillo hasta 30 %, rojo más. "
                       "Desviación poblacional: verde hasta 5 %, amarillo hasta 10 %. "
                       "Densidad = plantas por metro de surco / distancia entre surcos.", peq))

    # ------------------------------------------------------------------ una página por muestra
    for i, m in enumerate(muestras, 1):
        S.append(PageBreak())
        S.append(Paragraph(_t(f"Muestra {i}: {m['nombre']}" + (f" - {m['ambiente']}" if m.get("ambiente") else "")), h2))
        if m.get("fecha"):
            S.append(Paragraph(_t(f"Cargada el {m['fecha']}"), peq))
        t = m.get("tot")
        if t:
            k = [["Densidad", "Densidad", "Media", "Desvío", "CV", "Plantas"],
                 [_fmt(t["pl_ha"], 0, True) + " pl/ha", _fmt(t["pl_m"], 2) + " pl/m", _fmt(t["media_cm"]) + " cm",
                  _fmt(t["desvio_cm"]) + " cm", _fmt(t["cv"]) + " %", str(t["plantas"])]]
            ek = [("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]
            cc = _color(t["cv"], 22, 30)
            if cc:
                ek.append(("BACKGROUND", (4, 1), (4, 1), cc))
            S.append(Spacer(1, 3))
            S.append(_tabla(k, [W / 6] * 6, estilos=ek))
        S.append(Spacer(1, 6))
        alto = 13.5 * cm
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
