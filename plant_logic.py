"""Lógica de Plant Counter AI: detección, surcos, escala y estadísticas.

Sin dependencias de Streamlit, para poder probarla sola.
"""
import math

import cv2
import numpy as np


# ---------------------------------------------------------------- detección
def detectar_plantas(img_bgr, sensibilidad=35):
    """Devuelve una lista de plantas: dict(x, y, box) con (x, y) = tallo.

    Usa el índice de verdor ExG (2G - R - B), que aguanta mejor el sol fuerte
    y la sombra que un rango fijo de HSV. Las hojas de una misma planta se
    juntan dilatando la máscara.
    """
    h, w = img_bgr.shape[:2]
    b, g, r = [c.astype(np.int16) for c in cv2.split(img_bgr)]
    exg = 2 * g - r - b
    mask = ((exg > sensibilidad) & (g > 60) & (g > r + 8)).astype(np.uint8)

    d = max(2, int(round(w * 0.022)))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * d + 1, 2 * d + 1))
    unida = cv2.dilate(mask, k)
    n, lab = cv2.connectedComponents(unida, connectivity=8)

    min_px = max(15, int(w * h * 8e-6))
    sigma = max(2.0, w / 200)
    dens = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigma)

    plantas = []
    for i in range(1, n):
        comp = (lab == i) & (mask > 0)
        cnt = int(comp.sum())
        if cnt < min_px:
            continue
        ys, xs = np.nonzero(comp)
        # tallo = zona más densa de hojas dentro de la planta
        dv = dens[ys, xs]
        sel = dv >= 0.6 * dv.max()
        wgt = dv[sel]
        sx = float((xs[sel] * wgt).sum() / wgt.sum())
        sy = float((ys[sel] * wgt).sum() / wgt.sum())
        plantas.append({
            "x": sx, "y": sy, "px": cnt,
            "box": (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
            "manual": False,
        })
    plantas.sort(key=lambda p: (p["x"], p["y"]))
    return plantas


# ------------------------------------------------------------------- surcos
def _kmeans_1d(vals, k):
    lo, hi = vals.min(), vals.max()
    c = np.array([lo + (hi - lo) * (i + 0.5) / k for i in range(k)])
    lab = np.zeros(len(vals), int)
    for _ in range(20):
        lab = np.abs(vals[:, None] - c[None, :]).argmin(1)
        for i in range(k):
            if (lab == i).any():
                c[i] = vals[lab == i].mean()
    costo = float(((vals - c[lab]) ** 2).sum())
    return lab, c, costo


def _agrupar(plantas, n_surcos):
    x = np.array([p["x"] for p in plantas])
    y = np.array([p["y"] for p in plantas])
    mejor = None
    for s in np.arange(-0.5, 0.5001, 0.01):
        lab, c, costo = _kmeans_1d(x - s * y, n_surcos)
        if mejor is None or costo < mejor[2]:
            mejor = (lab, c, costo, s)
    lab, c, _, s = mejor
    orden = np.argsort(c)
    rango = {int(o): i for i, o in enumerate(orden)}
    for p, l in zip(plantas, lab):
        p["surco"] = rango[int(l)]
    return s


def asignar_surcos(plantas, n_surcos=2):
    """Agrupa las plantas en surcos (admite surcos algo inclinados) y marca
    como 'fuera' las que están lejos de todos los surcos (por ejemplo, una
    planta cortada de un tercer surco en el borde de la foto)."""
    for p in plantas:
        p["fuera"] = False
    if not plantas:
        return
    if len(plantas) < n_surcos + 1:
        for p in plantas:
            p["surco"] = 0
        return
    s = _agrupar(plantas, n_surcos)
    if n_surcos >= 2:
        cen = [np.median([p["x"] - s * p["y"] for p in plantas if p["surco"] == r] or [0])
               for r in range(n_surcos)]
        sep = float(np.median(np.diff(sorted(cen))))
        fuera = [p for p in plantas
                 if abs(p["x"] - s * p["y"] - cen[p["surco"]]) > 0.4 * sep]
        if fuera:
            for p in fuera:
                p["fuera"] = True
            dentro = [p for p in plantas if not p["fuera"]]
            if len(dentro) >= n_surcos + 1:
                _agrupar(dentro, n_surcos)
            for p in fuera:
                p["surco"] = -1


def lineas_iniciales(plantas, n_surcos, w, inclinadas=False, h=None):
    """Líneas de surco como (x_arriba, x_abajo). Verticales por defecto."""
    lineas = []
    for s in range(n_surcos):
        pts = [p for p in plantas if p.get("surco") == s]
        if not pts:
            xm = w * (s + 0.5) / n_surcos
            lineas.append((xm, xm))
            continue
        xm = float(np.mean([p["x"] for p in pts]))
        if inclinadas and len(pts) >= 3:
            ys = np.array([p["y"] for p in pts])
            xs = np.array([p["x"] for p in pts])
            a, b = np.polyfit(ys, xs, 1)
            lineas.append((float(b), float(a * h + b)))
        else:
            lineas.append((xm, xm))
    return lineas


# ------------------------------------------------------------------- escala
def modelo_distancia(lineas, h, w, entre_surcos_cm):
    """Devuelve dist(y1, y2) en cm a lo largo del surco.

    Líneas paralelas -> escala única (como SIMA).
    Líneas que se juntan -> corrige la perspectiva (foto inclinada).
    """
    n = len(lineas)

    def lx(i, y):
        t, b = lineas[i]
        return t + (b - t) * y / h

    def sp(y):
        return abs(lx(n - 1, y) - lx(0, y)) / (n - 1) / entre_surcos_cm

    s0 = sp(h / 2)
    k = (sp(h) - sp(0)) / h
    if s0 <= 0:
        return lambda a, b: float("nan")
    if abs(k * h / s0) <= 0.03:
        return lambda a, b: abs(b - a) / s0
    f = 0.6 * math.hypot(w, h)  # foco típico de celular (~26 mm equiv.)
    vh = -s0 / k
    tp = s0 / (k * f)
    A = f * math.sqrt(1 + tp * tp) / k
    return lambda a, b: abs(A * (1 / ((a - h / 2) - vh) - 1 / ((b - h / 2) - vh)))


# ------------------------------------------------------------ estadísticas
def calcular(plantas, lineas, h, w, entre_surcos_cm, largo_real_cm=None):
    n_surcos = len(lineas)
    dist = modelo_distancia(lineas, h, w, entre_surcos_cm)
    largo0 = dist(0, h)
    kf = (largo_real_cm / largo0) if largo_real_cm and largo_real_cm > 0 else 1.0
    largo = largo0 * kf

    surcos = []
    for s in range(n_surcos):
        pts = sorted([p for p in plantas if p.get("surco") == s], key=lambda p: p["y"])
        dd = [dist(pts[i]["y"], pts[i + 1]["y"]) * kf for i in range(len(pts) - 1)]
        media = float(np.mean(dd)) if dd else float("nan")
        desvio = float(np.std(dd, ddof=1)) if len(dd) > 1 else float("nan")
        plm = len(pts) / (largo / 100)
        surcos.append({
            "surco": s + 1, "plantas": len(pts), "dist_cm": dd,
            "media_cm": media, "desvio_cm": desvio,
            "cv": desvio / media * 100 if dd and media else float("nan"),
            "pl_m": plm, "pl_ha": plm / (entre_surcos_cm / 100) * 10000,
        })
    v = [s for s in surcos if not math.isnan(s["media_cm"])]
    tot = {
        "plantas": len(plantas), "largo_cm": largo, "largo_estimado_cm": largo0,
        "pl_m": float(np.mean([s["pl_m"] for s in surcos])),
        "pl_ha": float(np.mean([s["pl_ha"] for s in surcos])),
        "media_cm": float(np.mean([s["media_cm"] for s in v])) if v else float("nan"),
        "desvio_cm": float(np.mean([s["desvio_cm"] for s in v if not math.isnan(s["desvio_cm"])] or [float("nan")])),
    }
    tot["cv"] = tot["desvio_cm"] / tot["media_cm"] * 100 if v else float("nan")
    # variación de tamaño: CV del tamaño de los recuadros (lado del cuadrado de igual área).
    # Las plantas agregadas a mano no tienen recuadro y no cuentan.
    tam = [math.sqrt(max(1, p["box"][2] - p["box"][0]) * max(1, p["box"][3] - p["box"][1]))
           for p in plantas if p.get("box")]
    tot["tam_n"] = len(tam)
    tot["tam_cv"] = float(np.std(tam, ddof=1) / np.mean(tam) * 100) if len(tam) >= 3 else float("nan")
    todas = [d for s in surcos for d in s["dist_cm"]]
    mm = float(np.mean(todas)) if todas else float("nan")
    tot["dobles"] = sum(d < 0.5 * mm for d in todas) if todas else 0
    tot["baches"] = sum(d > 1.5 * mm for d in todas) if todas else 0
    return surcos, tot


def semaforo(valor, verde, amarillo):
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "⚪"
    return "🟢" if valor <= verde else ("🟡" if valor <= amarillo else "🔴")


# ------------------------------------------------------------------- dibujo
def dibujar(img_bgr, plantas, lineas, surcos, quitadas=(), ver_lineas=True, ver_cajas=True, ver_dist=True):
    """Dibuja las capas pedidas sobre la foto. Con las tres en False devuelve la original."""
    out = img_bgr.copy()
    h, w = out.shape[:2]
    u = w / 1200
    colores = [(60, 60, 235), (235, 140, 30), (0, 140, 255), (160, 40, 140), (140, 140, 0), (60, 80, 110)]
    for (t, b) in (lineas if ver_lineas else []):
        cv2.line(out, (int(t), 0), (int(b), h), (0, 230, 255), max(2, int(3 * u)))
    por_surco = {}
    for i, p in enumerate(plantas):
        p["id"] = i + 1
        if i in quitadas:
            continue
        if not ver_cajas:
            continue
        col = colores[p.get("surco", 0) % 6]
        bx = p["box"] if p.get("box") else (p["x"] - 24 * u, p["y"] - 24 * u, p["x"] + 24 * u, p["y"] + 24 * u)
        cv2.rectangle(out, (int(bx[0]), int(bx[1])), (int(bx[2]), int(bx[3])), col, max(2, int(3 * u)))
        cv2.circle(out, (int(p["x"]), int(p["y"])), max(4, int(7 * u)), (255, 90, 30), -1)
        cv2.circle(out, (int(p["x"]), int(p["y"])), max(4, int(7 * u)), (255, 255, 255), 1)
        cv2.putText(out, str(p["id"]), (int(bx[0]), max(15, int(bx[1]) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8 * u, (255, 255, 255), max(2, int(3 * u)))
        cv2.putText(out, str(p["id"]), (int(bx[0]), max(15, int(bx[1]) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8 * u, (0, 0, 0), max(1, int(1.5 * u)))
        por_surco.setdefault(p.get("surco", 0), []).append(p)
    for s, pts in (por_surco.items() if (ver_cajas and ver_dist) else []):
        pts = sorted(pts, key=lambda p: p["y"])
        dd = surcos[s]["dist_cm"] if s < len(surcos) else []
        for i in range(len(pts) - 1):
            a, c = pts[i], pts[i + 1]
            cv2.line(out, (int(a["x"]), int(a["y"])), (int(c["x"]), int(c["y"])), colores[s % 6], max(1, int(2 * u)))
            if i < len(dd):
                mx, my = int((a["x"] + c["x"]) / 2) + int(8 * u), int((a["y"] + c["y"]) / 2)
                t = f"{dd[i]:.0f}"
                (tw, th), _ = cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.9 * u, 2)
                cv2.rectangle(out, (mx - 3, my - th - 3), (mx + tw + 3, my + 5), (0, 0, 0), -1)
                cv2.putText(out, t, (mx, my), cv2.FONT_HERSHEY_SIMPLEX, 0.9 * u, (255, 255, 255), 2)
    return out
