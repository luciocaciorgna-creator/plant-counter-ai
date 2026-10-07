import hashlib

import cv2
import numpy as np
import pandas as pd
import json
from pathlib import Path
import streamlit as st
from PIL import Image
from streamlit_image_coordinates import streamlit_image_coordinates

import plant_logic as pl

st.set_page_config(page_title="Plant Counter AI V1.1", layout="wide")
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
st.title("🌱 Plant Counter AI")
st.subheader("Stand de plantas")

if "establecimientos" not in st.session_state:

    st.session_state.establecimientos = {
        "Establecimiento 1": [
            "Lote 1"
        ]
    }

st.sidebar.header("🏢 Gestión")

establecimiento = st.sidebar.selectbox(
    "Establecimiento",
    list(
        st.session_state.establecimientos.keys()
    )
)

nuevo_est = st.sidebar.text_input(
    "Nuevo establecimiento"
)

if st.sidebar.button(
    "Agregar establecimiento"
):

    if (
        nuevo_est
        and
        nuevo_est
        not in st.session_state.establecimientos
    ):

        st.session_state.establecimientos[
            nuevo_est
        ] = []

        st.rerun()

lote = st.sidebar.selectbox(
    "Lote",
    st.session_state.establecimientos[
        establecimiento
    ]
)

nuevo_lote = st.sidebar.text_input(
    "Nuevo lote"
)

if st.sidebar.button(
    "Agregar lote"
):

    if nuevo_lote:

        st.session_state.establecimientos[
            establecimiento
        ].append(
            nuevo_lote
        )

        st.rerun()

st.info(
    f"🏢 {establecimiento} | 📍 {lote}"
)

# ------------------------------------------------------------------ opciones
with st.sidebar:
    st.header("Datos del lote")
    lote = st.text_input("Lote", "")
    distancia_surco_cm = st.number_input("Distancia entre surcos (cm)", 10.0, 150.0, 52.0, 0.5)
    n_surcos = int(st.number_input("Surcos en la foto", 2, 6, 2, 1))
    objetivo = st.number_input("Densidad objetivo (pl/ha, opcional)", 0, 300000, 0, 1000)
      st.header("Ajustes")

    mostrar_detecciones = st.toggle(
        "👁 Mostrar detecciones",
        value=True
    )

    sensibilidad = int(
        st.slider(
            "Sensibilidad de detección",
            15,
            60,
            35,
            help="Más bajo detecta más verde (más plantas, más falsos). Más alto es más exigente."
        )
    )

    inclinada = st.checkbox(
        "Fotos inclinadas (corregir perspectiva)",
        False,
        help="Inclina las líneas de surco siguiendo las plantas y corrige la escala. Con las fotos derechas, dejalo apagado."
    )
    largo_real = st.number_input("Largo real de la foto (cm, opcional)", 0, 500, 0, 1,
                                 help="Si sabés cuántos cm de surco entran en tus fotos (medido una vez con cinta, "
                                      "a la altura a la que sacás siempre), cargalo y la densidad sale exacta. "
                                      "Se aplica a todas las muestras.")

archivos = st.file_uploader("Subí las fotos (una por muestra)", type=["jpg", "jpeg", "png"],
                            accept_multiple_files=True)


@st.cache_data(show_spinner="Detectando plantas...")
def procesar(datos: bytes, sens: int, n: int):
    img = cv2.imdecode(np.frombuffer(datos, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    if w > 1400:
        img = cv2.resize(img, (1400, int(h * 1400 / w)), interpolation=cv2.INTER_AREA)
    plantas = pl.detectar_plantas(img, sens)
    pl.asignar_surcos(plantas, n)
    return img, plantas


def analizar(i, archivo):
    """Procesa una muestra aplicando las correcciones manuales guardadas."""
    datos = archivo.getvalue()
    fid = f"{hashlib.md5(datos).hexdigest()[:10]}_{i}"
    img, detectadas = procesar(datos, sensibilidad, n_surcos)
    h, w = img.shape[:2]
    ids_validos = [k + 1 for k, p in enumerate(detectadas) if not p["fuera"]]
    qkey = f"quitar_{fid}_{sensibilidad}_{n_surcos}"
    quitar_ids = [k for k in st.session_state.get(qkey, []) if k in ids_validos]
    quitadas = {k - 1 for k in quitar_ids} | {k for k, p in enumerate(detectadas) if p["fuera"]}
    auto = [p for k, p in enumerate(detectadas) if k not in quitadas]
    lineas = pl.lineas_iniciales(auto, n_surcos, w, inclinada, h)
    manuales = []
    for (mx, my) in st.session_state.get(f"ag_{fid}", []):
        xs = [t + (b - t) * my / h for (t, b) in lineas]
        manuales.append({"x": mx, "y": my, "box": None, "manual": True, "fuera": False,
                         "surco": int(np.argmin([abs(mx - x) for x in xs]))})
    todas = detectadas + manuales
    activas = [p for k, p in enumerate(todas) if k not in quitadas]
    m = {"fid": fid, "nombre": archivo.name, "img": img, "h": h, "w": w, "ids": ids_validos, "qkey": qkey,
         "surcos": None, "tot": None, "pil": None}
    if len(activas) >= 2:
        surcos, tot = pl.calcular(activas, lineas, h, w, float(distancia_surco_cm),
                                  float(largo_real) if largo_real > 0 else None)
      if mostrar_detecciones:

    out = pl.dibujar(
        img,
        todas,
        lineas,
        surcos,
        quitadas
    )

else:

    out = img.copy()
        m.update(surcos=surcos, tot=tot, pil=Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)))
    else:
        m["pil"] = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    return m


if not archivos:
    st.info("Subí una o más fotos para comenzar. Lo ideal: fotos paralelas al suelo, con 2 surcos, "
            "y varias por lote (SIMA recomienda cerca de 10 m de surco en total).")
    st.stop()

muestras = [analizar(i, a) for i, a in enumerate(archivos)]
ok = [m for m in muestras if m["tot"]]

# ------------------------------------------------------- resumen general
st.header("📈 Resumen del lote" + (f": {lote}" if lote else ""))
if not ok:
    st.warning("No pude calcular ninguna muestra. Probá bajar la sensibilidad o agregar plantas a mano.")
else:
    filas = []
    for k, m in enumerate(muestras):
        t = m["tot"]
        if not t:
            continue
        filas.append({
            "Muestra": f"{k + 1}. {m['nombre']}", "Plantas": t["plantas"],
            "m de surco": round(t["largo_cm"] * n_surcos / 100, 1),
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
    csv = tabla.assign(Lote=lote or "Sin nombre", Entre_surcos_cm=distancia_surco_cm)
    st.download_button("Descargar resumen (CSV)", csv.to_csv(index=False).encode("utf-8"),
                       "stand_plantas.csv", "text/csv")

# ------------------------------------------------------ detalle por muestra
st.header("🔍 Detalle por muestra")
tabs = st.tabs([f"Muestra {k + 1}" for k in range(len(muestras))])
for k, (tab, m) in enumerate(zip(tabs, muestras)):
    with tab:
        fid = m["fid"]
        col_img, col_res = st.columns([3, 2])
        with col_img:
            modo = st.toggle("Modo agregar planta (tocá el tallo en la foto)", key=f"tg_{fid}")
            click = streamlit_image_coordinates(m["pil"], key=f"img_{fid}", width=650)
            if modo and click and click.get("unix_time") != st.session_state.get(f"uc_{fid}"):
                st.session_state[f"uc_{fid}"] = click["unix_time"]
                st.session_state.setdefault(f"ag_{fid}", []).append(
                    (click["x"] * m["w"] / click["width"], click["y"] * m["h"] / click["height"]))
                st.rerun()
            st.multiselect("Quitar plantas (por número)", m["ids"], key=m["qkey"],
                           help="Los números aparecen sobre cada planta en la foto.")
            if st.session_state.get(f"ag_{fid}") and st.button("Deshacer última planta agregada", key=f"un_{fid}"):
                st.session_state[f"ag_{fid}"].pop()
                st.rerun()
        with col_res:
            t = m["tot"]
            if not t:
                st.warning("Menos de 2 plantas en esta muestra.")
                continue
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
            filas_s = [{"Surco": str(s["surco"]), "Plantas": s["plantas"], "pl/m": round(s["pl_m"], 2),
                        "pl/ha": round(s["pl_ha"]), "Media (cm)": round(s["media_cm"], 1),
                        "Desvío (cm)": round(s["desvio_cm"], 1), "CV (%)": round(s["cv"], 1)}
                       for s in m["surcos"]]
            st.dataframe(pd.DataFrame(filas_s), hide_index=True)
