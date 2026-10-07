import hashlib
import math
import time

import cv2
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image

import plant_logic as pl
import storage as sto
import viewer as vw

st.set_page_config(page_title="Plant Counter AI V1.2", layout="wide")
st.title("🌱 Plant Counter AI")
st.subheader("Stand de plantas")

sb = st.sidebar

# ============================================================ establecimiento / lote
sb.header("🏢 Establecimiento y lote")
for k in ("sel_est", "sel_lote"):  # selección pendiente tras crear uno nuevo
    if f"_next_{k}" in st.session_state:
        st.session_state[k] = st.session_state.pop(f"_next_{k}")

estructura = sto.cargar_estructura()
ests = list(estructura.keys())
est = sb.selectbox("Establecimiento", ests, key="sel_est")
with sb.form("f_est", clear_on_submit=True):
    nuevo_est = st.text_input("Nuevo establecimiento")
    if st.form_submit_button("Agregar establecimiento") and sto.agregar_establecimiento(nuevo_est):
        st.session_state["_next_sel_est"] = nuevo_est.strip()
        st.rerun()

lotes = list(estructura.get(est, {}).keys())
lote = sb.selectbox("Lote", lotes, key="sel_lote") if lotes else None
with sb.form("f_lote", clear_on_submit=True):
    nuevo_lote = st.text_input("Nuevo lote")
    if st.form_submit_button("Agregar lote") and sto.agregar_lote(est, nuevo_lote):
        st.session_state["_next_sel_lote"] = nuevo_lote.strip()
        st.rerun()

if lote is None:
    st.info("Este establecimiento todavía no tiene lotes. Agregá uno desde la barra lateral.")
    st.stop()

# ----------------------------------------------------- configuración (se guarda por lote)
cfg = sto.cfg_lote(est, lote)
pref = f"{est}|{lote}|"
sb.header("Datos del lote")
distancia_surco_cm = sb.number_input("Distancia entre surcos (cm)", 10.0, 150.0,
                                     float(cfg["entre_surcos"]), 0.5, key=pref + "entre")
n_surcos = int(sb.number_input("Surcos en la foto", 2, 6, int(cfg["n_surcos"]), 1, key=pref + "n"))
objetivo = sb.number_input("Densidad objetivo (pl/ha, opcional)", 0, 300000, int(cfg["objetivo"]), 1000,
                           key=pref + "obj")
sb.header("Ajustes")
inclinada = sb.checkbox("Fotos inclinadas (corregir perspectiva)", bool(cfg.get("inclinada", False)),
                        key=pref + "inc",
                        help="Inclina las líneas de surco siguiendo las plantas y corrige la escala. "
                             "Con las fotos derechas, dejalo apagado.")
largo_real = sb.number_input("Largo real de la foto (cm, opcional)", 0, 500, int(cfg.get("largo_real", 0)), 1,
                             key=pref + "lr",
                             help="Si sabés cuántos cm de surco entran en tus fotos (medido una vez con cinta, "
                                  "a la altura a la que sacás siempre), cargalo y la densidad sale exacta. "
                                  "Se aplica a todas las muestras del lote.")
sens_nueva = int(sb.slider("Sensibilidad para fotos nuevas", 15, 60, 35, key="sens",
                           help="Más bajo detecta más verde (más plantas, más falsos). Cada foto guardada "
                                "conserva la sensibilidad con la que se cargó."))
cfg_actual = {"entre_surcos": float(distancia_surco_cm), "n_surcos": n_surcos, "objetivo": int(objetivo),
              "inclinada": bool(inclinada), "largo_real": int(largo_real)}
if any(cfg.get(k) != v for k, v in cfg_actual.items()):
    sto.guardar_cfg(est, lote, cfg_actual)

# ----------------------------------------------------------------------- respaldo
with sb.expander("💾 Respaldo de datos"):
    st.caption("Streamlit Cloud borra los archivos cuando la app se reinicia. Bajá un respaldo de vez en cuando "
               "y restauralo si hace falta.")
    if st.checkbox("Preparar respaldo (.zip)", key="prep_zip"):
        st.download_button("Descargar respaldo", sto.exportar_zip(), "plant_counter_respaldo.zip", "application/zip")
    zip_sub = st.file_uploader("Restaurar respaldo", type=["zip"], key="zip_up")
    if zip_sub is not None and st.button("Restaurar ahora"):
        sto.importar_zip(zip_sub.getvalue())
        st.rerun()

st.info(f"🏢 {est}  |  📍 {lote}")

# ------------------------------------------------------------------ subida de fotos
st.session_state.setdefault("up_n", 0)
archivos = st.file_uploader("Subí fotos nuevas (una por muestra)", type=["jpg", "jpeg", "png"],
                            accept_multiple_files=True, key=f"up_{st.session_state['up_n']}")


@st.cache_data(show_spinner=False)
def comprimir(datos: bytes):
    return sto.comprimir(datos)


@st.cache_data(show_spinner="Detectando plantas...")
def procesar(datos: bytes, sens: int, n: int):
    img = cv2.imdecode(np.frombuffer(datos, np.uint8), cv2.IMREAD_COLOR)
    plantas = pl.detectar_plantas(img, sens)
    pl.asignar_surcos(plantas, n)
    return img, plantas


def fuentes_del_lote():
    out = []
    for m in sto.listar_muestras(est, lote):
        out.append({"fid": f"g{m['id']}", "sid": m["id"], "nombre": m.get("nombre", "foto"),
                    "datos": sto.leer_foto(est, lote, m["id"]), "meta": m, "sens": int(m.get("sens", 35)),
                    "guardada": True})
    for i, a in enumerate(archivos or []):
        datos = comprimir(a.getvalue())
        out.append({"fid": f"n{hashlib.md5(datos).hexdigest()[:10]}_{i}", "sid": None, "nombre": a.name,
                    "datos": datos, "meta": None, "sens": sens_nueva, "guardada": False})
    return out


def analizar(f):
    fid = f["fid"]
    img, detectadas = procesar(f["datos"], f["sens"], n_surcos)
    h, w = img.shape[:2]
    ids_validos = [k + 1 for k, p in enumerate(detectadas) if not p["fuera"]]
    qkey = f"quitar_{fid}_{f['sens']}"
    akey = f"ag_{fid}"
    if f["guardada"]:  # primera vez en esta sesión: cargar correcciones guardadas
        st.session_state.setdefault(qkey, list(f["meta"].get("quitar", [])))
        st.session_state.setdefault(akey, [tuple(x) for x in f["meta"].get("agregadas", [])])
    quitar_ids = [k for k in st.session_state.get(qkey, []) if k in ids_validos]
    st.session_state[qkey] = quitar_ids  # evita ids viejos en el multiselect
    quitadas = {k - 1 for k in quitar_ids} | {k for k, p in enumerate(detectadas) if p["fuera"]}
    auto = [p for k, p in enumerate(detectadas) if k not in quitadas]
    lineas = pl.lineas_iniciales(auto, n_surcos, w, inclinada, h)
    manuales = []
    for (mx, my) in st.session_state.get(akey, []):
        xs = [t + (b - t) * my / h for (t, b) in lineas]
        manuales.append({"x": mx, "y": my, "box": None, "manual": True, "fuera": False,
                         "surco": int(np.argmin([abs(mx - x) for x in xs]))})
    todas = detectadas + manuales
    activas = [p for k, p in enumerate(todas) if k not in quitadas]
    agregadas = [[round(x, 1), round(y, 1)] for x, y in st.session_state.get(akey, [])]
    m = {**f, "img": img, "h": h, "w": w, "ids": ids_validos, "qkey": qkey, "akey": akey,
         "quitar": sorted(quitar_ids), "agregadas": agregadas, "ndet": len(detectadas), "surcos": None, "tot": None,
         "draw": (todas, lineas, quitadas)}
    if len(activas) >= 2:
        m["surcos"], m["tot"] = pl.calcular(activas, lineas, h, w, float(distancia_surco_cm),
                                            float(largo_real) if largo_real > 0 else None)
        m["draw"] = (todas, lineas, quitadas)
    if f["guardada"] and (m["quitar"] != sorted(f["meta"].get("quitar", []))
                          or agregadas != f["meta"].get("agregadas", [])):
        sto.actualizar_muestra(est, lote, f["sid"], {"quitar": m["quitar"], "agregadas": agregadas})
    return m


fuentes = fuentes_del_lote()
if not fuentes:
    st.info("Subí una o más fotos para comenzar. Lo ideal: fotos paralelas al suelo, con 2 surcos, "
            "y varias por lote (SIMA recomienda cerca de 10 m de surco en total).")
    st.stop()

muestras = [analizar(f) for f in fuentes]
nuevas = [m for m in muestras if not m["guardada"]]
ok = [m for m in muestras if m["tot"]]

if nuevas:
    st.warning(f"{len(nuevas)} foto(s) todavía sin guardar. Corregí las plantas si hace falta y guardalas en el lote.")
    if st.button(f"💾 Guardar {len(nuevas)} foto(s) en {est} / {lote}", type="primary"):
        for m in nuevas:
            sto.guardar_muestra(est, lote, m["datos"], {
                "nombre": m["nombre"], "sens": m["sens"], "quitar": m["quitar"],
                "agregadas": m["agregadas"], "fecha": time.strftime("%d/%m/%Y %H:%M")})
        st.session_state["up_n"] += 1
        st.rerun()

# ================================================================ resumen del lote
st.header(f"📈 Resumen del lote: {lote}")
if not ok:
    st.warning("No pude calcular ninguna muestra. Probá agregar plantas a mano.")
else:
    filas = []
    for k, m in enumerate(muestras):
        t = m["tot"]
        if not t:
            continue
        filas.append({
            "Muestra": f"{k + 1}. {m['nombre']}" + ("" if m["guardada"] else " (sin guardar)"),
            "Plantas": t["plantas"], "m de surco": round(t["largo_cm"] * n_surcos / 100, 1),
            "pl/m": round(t["pl_m"], 2), "pl/ha": round(t["pl_ha"]),
            "Media (cm)": round(t["media_cm"], 1), "Desvío (cm)": round(t["desvio_cm"], 1),
            "CV (%)": round(t["cv"], 1), "CV": pl.semaforo(t["cv"], 22, 30),
        })
    df = pd.DataFrame(filas)
    prom = {
        "pl_m": df["pl/m"].mean(), "pl_ha": df["pl/ha"].mean(), "media": df["Media (cm)"].mean(),
        "desvio": df["Desvío (cm)"].mean(), "cv": df["CV (%)"].mean(),
        "plantas": int(df["Plantas"].sum()), "metros": df["m de surco"].sum(),
        "ent_sd": df["pl/ha"].std(ddof=1) if len(df) > 1 else float("nan"),
    }
    prom["ent_cv"] = prom["ent_sd"] / prom["pl_ha"] * 100 if len(df) > 1 else float("nan")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Densidad promedio", f"{prom['pl_ha']:,.0f} pl/ha")
    c2.metric("Densidad promedio", f"{prom['pl_m']:.2f} pl/m")
    c3.metric("Media entre plantas", f"{prom['media']:.1f} cm")
    c4.metric("Desvío promedio", f"{prom['desvio']:.1f} cm")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("CV promedio", f"{prom['cv']:.1f} % {pl.semaforo(prom['cv'], 22, 30)}")
    d2.metric("Muestras", len(df))
    d3.metric("Metros de surco medidos", f"{prom['metros']:.1f} m")
    d4.metric("Plantas contadas", prom["plantas"])
    if objetivo > 0:
        dev = (prom["pl_ha"] - objetivo) / objetivo * 100
        e1, e2 = st.columns(2)
        e1.metric("Desviación poblacional", f"{dev:+.1f} % {pl.semaforo(abs(dev), 5, 10)}")
        e2.metric("Coeficiente de logro", f"{prom['pl_ha'] / objetivo * 100:.1f} %")

    fila_prom = {"Muestra": "PROMEDIO", "Plantas": prom["plantas"], "m de surco": round(prom["metros"], 1),
                 "pl/m": round(prom["pl_m"], 2), "pl/ha": round(prom["pl_ha"]),
                 "Media (cm)": round(prom["media"], 1), "Desvío (cm)": round(prom["desvio"], 1),
                 "CV (%)": round(prom["cv"], 1), "CV": pl.semaforo(prom["cv"], 22, 30)}
    tabla = pd.concat([df, pd.DataFrame([fila_prom])], ignore_index=True)
    st.dataframe(tabla, hide_index=True)
    if len(df) > 1:
        st.caption(f"Variación de la densidad entre muestras: desvío {prom['ent_sd']:,.0f} pl/ha "
                   f"(CV {prom['ent_cv']:.1f} %). El promedio es el promedio simple de las muestras.")
    if prom["metros"] < 10:
        st.caption("SIMA recomienda cerca de 10 m de surco por punto de muestreo: con menos, "
                   "el promedio es poco representativo.")
    csv = tabla.assign(Establecimiento=est, Lote=lote, Entre_surcos_cm=distancia_surco_cm)
    st.download_button("Descargar resumen (CSV)", csv.to_csv(index=False).encode("utf-8"),
                       f"stand_{lote}.csv", "text/csv")

# ============================================================== detalle por muestra
st.header("🔍 Detalle por muestra")
fids = [m["fid"] for m in muestras]
nombres = {m["fid"]: f"{k + 1}. {m['nombre']}" + ("" if m["guardada"] else " (sin guardar)")
           for k, m in enumerate(muestras)}
skey = f"selm_{est}_{lote}"
if st.session_state.get(skey) not in fids:
    st.session_state.pop(skey, None)
fid_sel = st.selectbox("Elegí la muestra", fids, format_func=lambda f: nombres[f], key=skey)
m = muestras[fids.index(fid_sel)]
fid = m["fid"]
todas, lineas, quitadas = m["draw"]
surcos_dib = m["surcos"] or []

c_a, c_b, c_c, c_d = st.columns(4)
v_lin = c_a.toggle("Líneas de surco", True, key=f"vl_{fid}")
v_caj = c_b.toggle("Cajas y puntos", True, key=f"vc_{fid}")
v_dis = c_c.toggle("Distancias", True, key=f"vd_{fid}")
alto = c_d.slider("Alto del visor", 350, 900, 560, 50, key=f"alto_{fid}")
modo_tap = st.radio("Al tocar la foto:", ["Solo mover y hacer zoom", "Agregar planta", "Quitar planta"],
                    horizontal=True, key=f"tap_{fid}",
                    help="Con 'Solo mover y hacer zoom' los toques no cambian nada.")
st.caption("Pellizcá con dos dedos para hacer zoom y arrastrá para moverte (o usá ＋ y －). "
           "Con zoom 1x un dedo desplaza la página. El botón 👁 alterna entre procesada y original "
           "en la misma posición, para comparar.")

if m["tot"]:
    proc_bgr = pl.dibujar(m["img"], todas, lineas, surcos_dib, quitadas, v_lin, v_caj, v_dis)
else:
    proc_bgr = m["img"]
click = vw.foto_viewer(m["img"], proc_bgr, alto, modo_tap != "Solo mover y hacer zoom", fid, f"vw_{fid}")
if click and click.get("t") != st.session_state.get(f"uc_{fid}"):
    st.session_state[f"uc_{fid}"] = click.get("t")
    cx, cy = float(click["x"]), float(click["y"])
    if modo_tap == "Agregar planta":
        st.session_state.setdefault(m["akey"], []).append((cx, cy))
        st.rerun()
    elif modo_tap == "Quitar planta":
        cand = [(math.hypot(p["x"] - cx, p["y"] - cy), k) for k, p in enumerate(todas) if k not in quitadas]
        if cand:
            d, k = min(cand)
            if d <= 0.06 * m["w"]:
                if k < m["ndet"]:
                    st.session_state[m["qkey"]] = sorted(set(st.session_state.get(m["qkey"], [])) | {k + 1})
                else:
                    st.session_state[m["akey"]].pop(k - m["ndet"])
                st.rerun()
            else:
                st.toast("No hay ninguna planta cerca de ese punto.")

col_ctl, col_res = st.columns([3, 2])
with col_ctl:
    st.multiselect("Quitar plantas (por número)", m["ids"], key=m["qkey"],
                   help="Los números aparecen sobre cada planta si 'Cajas y puntos' está prendido.")
    if st.session_state.get(m["akey"]) and st.button("Deshacer última planta agregada", key=f"un_{fid}"):
        st.session_state[m["akey"]].pop()
        st.rerun()
    if m["guardada"]:
        st.caption(f"Guardada el {m['meta'].get('fecha', '-')} (sensibilidad {m['sens']}). "
                   "Las correcciones se guardan solas.")
        if st.session_state.get(f"del_{fid}"):
            if st.button("⚠️ Confirmar: eliminar esta muestra", key=f"dc_{fid}"):
                sto.eliminar_muestra(est, lote, m["sid"])
                st.session_state.pop(f"del_{fid}", None)
                st.rerun()
        elif st.button("🗑️ Eliminar muestra", key=f"dl_{fid}"):
            st.session_state[f"del_{fid}"] = True
            st.rerun()
    else:
        st.caption("Muestra sin guardar: usá el botón de guardar de arriba.")
with col_res:
    t = m["tot"]
    if not t:
        st.warning("Menos de 2 plantas en esta muestra.")
    else:
        a, b = st.columns(2)
        a.metric("Densidad", f"{t['pl_m']:.2f} pl/m")
        b.metric("Densidad", f"{t['pl_ha']:,.0f} pl/ha")
        a.metric("Media entre plantas", f"{t['media_cm']:.1f} cm")
        b.metric("Desvío", f"{t['desvio_cm']:.1f} cm")
        a.metric("CV", f"{t['cv']:.1f} % {pl.semaforo(t['cv'], 22, 30)}")
        b.metric("Plantas", t["plantas"])
        st.caption(f"Largo de surco en la foto: {t['largo_cm']:.0f} cm"
                   + (f" (cargado por vos; la app estimaba {t['largo_estimado_cm']:.0f} cm)"
                      if largo_real > 0 else " (estimado)")
                   + f". Posibles dobles: {t['dobles']}. Baches: {t['baches']}.")
        filas_s = [{"Surco": str(s_["surco"]), "Plantas": s_["plantas"], "pl/m": round(s_["pl_m"], 2),
                    "pl/ha": round(s_["pl_ha"]), "Media (cm)": round(s_["media_cm"], 1),
                    "Desvío (cm)": round(s_["desvio_cm"], 1), "CV (%)": round(s_["cv"], 1)}
                   for s_ in m["surcos"]]
        st.dataframe(pd.DataFrame(filas_s), hide_index=True)
