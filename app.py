import hashlib

import cv2
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_image_coordinates import streamlit_image_coordinates

import plant_logic as pl

st.set_page_config(page_title="Plant Counter AI V1.0", layout="wide")
st.title("🌱 Plant Counter AI")
st.subheader("Stand de plantas")

# ------------------------------------------------------------------ opciones
with st.sidebar:
    st.header("Datos de la muestra")
    lote = st.text_input("Lote", "")
    distancia_surco_cm = st.number_input("Distancia entre surcos (cm)", 10.0, 150.0, 52.0, 0.5)
    n_surcos = st.number_input("Surcos en la foto", 2, 6, 2, 1)
    objetivo = st.number_input("Densidad objetivo (pl/ha, opcional)", 0, 300000, 0, 1000)
    st.header("Ajustes")
    sensibilidad = st.slider("Sensibilidad de detección", 15, 60, 35,
                             help="Más bajo detecta más verde (más plantas, más falsos). Más alto es más exigente.")
    inclinada = st.checkbox("Foto inclinada (corregir perspectiva)", False,
                            help="Inclina las líneas de surco siguiendo las plantas y corrige la escala. "
                                 "Con la foto derecha, dejalo apagado.")
    largo_real = st.number_input("Largo real de la foto (cm, opcional)", 0, 500, 0, 1,
                                 help="Si sabés cuántos cm de surco entran en tu foto (por ejemplo, midiendo una vez "
                                      "con cinta a la altura a la que sacás siempre), cargalo y la densidad sale exacta.")

uploaded_file = st.file_uploader("Subí una foto", type=["jpg", "jpeg", "png"])


@st.cache_data(show_spinner="Detectando plantas...")
def procesar(datos: bytes, sens: int, n: int):
    img = cv2.imdecode(np.frombuffer(datos, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    if w > 1400:
        img = cv2.resize(img, (1400, int(h * 1400 / w)), interpolation=cv2.INTER_AREA)
    plantas = pl.detectar_plantas(img, sens)
    pl.asignar_surcos(plantas, n)
    return img, plantas


if uploaded_file is None:
    st.info("Subí una imagen para comenzar. Lo ideal: foto paralela al suelo, con 2 surcos, y varias fotos por lote.")
    st.stop()

datos = uploaded_file.getvalue()
fid = hashlib.md5(datos).hexdigest()
if st.session_state.get("fid") != fid:
    st.session_state.update(fid=fid, agregadas=[], ultimo_click=None)

img, detectadas = procesar(datos, int(sensibilidad), int(n_surcos))
h, w = img.shape[:2]
n_surcos = int(n_surcos)

# ------------------------------------------------- correcciones manuales
ids_validos = [i + 1 for i, p in enumerate(detectadas) if not p["fuera"]]
qkey = f"quitar_{fid}_{int(sensibilidad)}_{n_surcos}"
quitar_ids = [i for i in st.session_state.get(qkey, []) if i in ids_validos]
quitadas = {i - 1 for i in quitar_ids} | {i for i, p in enumerate(detectadas) if p["fuera"]}

auto_activas = [p for i, p in enumerate(detectadas) if i not in quitadas]
if len(auto_activas) < 2:
    st.warning("Detecté menos de 2 plantas. Probá bajar la sensibilidad o agregá plantas a mano.")
lineas = pl.lineas_iniciales(auto_activas, n_surcos, w, inclinada, h)

manuales = []
for (mx, my) in st.session_state["agregadas"]:
    xs = [t + (b - t) * my / h for (t, b) in lineas]
    manuales.append({"x": mx, "y": my, "box": None, "manual": True, "fuera": False,
                     "surco": int(np.argmin([abs(mx - x) for x in xs]))})
todas = detectadas + manuales
activas = [p for i, p in enumerate(todas) if i not in quitadas]

if len(activas) < 2:
    st.stop()

surcos, tot = pl.calcular(activas, lineas, h, w, float(distancia_surco_cm),
                          float(largo_real) if largo_real > 0 else None)
out = pl.dibujar(img, todas, lineas, surcos, quitadas)
pil = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))

# --------------------------------------------------------------- pantalla
col_img, col_res = st.columns([3, 2])

with col_img:
    modo_agregar = st.toggle("Modo agregar planta (tocá el tallo en la foto)")
    click = streamlit_image_coordinates(pil, key=f"img_{fid}", width=700)
    if modo_agregar and click and click.get("unix_time") != st.session_state["ultimo_click"]:
        st.session_state["ultimo_click"] = click["unix_time"]
        st.session_state["agregadas"].append((click["x"] * w / click["width"], click["y"] * h / click["height"]))
        st.rerun()

    st.multiselect("Quitar plantas (por número)", ids_validos, key=qkey,
                   help="Los números aparecen sobre cada planta en la foto.")
    if st.session_state["agregadas"] and st.button("Deshacer última planta agregada"):
        st.session_state["agregadas"].pop()
        st.rerun()

with col_res:
    st.subheader("📊 Resultados")
    c1, c2 = st.columns(2)
    c1.metric("Densidad", f"{tot['pl_m']:.2f} pl/m")
    c2.metric("Densidad", f"{tot['pl_ha']:,.0f} pl/ha")
    c1.metric("Media entre plantas", f"{tot['media_cm']:.1f} cm")
    c2.metric("Desvío", f"{tot['desvio_cm']:.1f} cm")
    cv_txt = f"{tot['cv']:.1f} % {pl.semaforo(tot['cv'], 22, 30)}"
    c1.metric("Coeficiente de variación", cv_txt)
    c2.metric("Plantas contadas", tot["plantas"])

    if objetivo > 0:
        dev = (tot["pl_ha"] - objetivo) / objetivo * 100
        c1.metric("Desviación poblacional", f"{dev:+.1f} % {pl.semaforo(abs(dev), 5, 10)}")
        c2.metric("Coeficiente de logro", f"{tot['pl_ha'] / objetivo * 100:.1f} %")

    st.caption(f"Largo de surco en la foto: {tot['largo_cm']:.0f} cm"
               + (f" (cargado por vos; la app estimaba {tot['largo_estimado_cm']:.0f} cm)" if largo_real > 0 else " (estimado)")
               + f". Posibles dobles: {tot['dobles']}. Baches: {tot['baches']}.")

st.subheader("Resultados por surco")
filas = [{"Surco": str(s["surco"]), "Plantas": s["plantas"], "pl/m": round(s["pl_m"], 2), "pl/ha": round(s["pl_ha"]),
          "Media (cm)": round(s["media_cm"], 1), "Desvío (cm)": round(s["desvio_cm"], 1),
          "CV (%)": round(s["cv"], 1)} for s in surcos]
filas.append({"Surco": "Promedio", "Plantas": tot["plantas"], "pl/m": round(tot["pl_m"], 2),
              "pl/ha": round(tot["pl_ha"]), "Media (cm)": round(tot["media_cm"], 1),
              "Desvío (cm)": round(tot["desvio_cm"], 1), "CV (%)": round(tot["cv"], 1)})
st.dataframe(pd.DataFrame(filas), hide_index=True)

# --------------------------------------------- varias fotos por lote
st.subheader("Mediciones de esta sesión")
if "mediciones" not in st.session_state:
    st.session_state["mediciones"] = []
if st.button("Guardar medición"):
    st.session_state["mediciones"].append({
        "lote": lote or "Sin nombre", "plantas": tot["plantas"], "largo_cm": round(tot["largo_cm"]),
        "pl_m": round(tot["pl_m"], 2), "pl_ha": round(tot["pl_ha"]),
        "media_cm": round(tot["media_cm"], 1), "desvio_cm": round(tot["desvio_cm"], 1),
        "cv": round(tot["cv"], 1), "entre_surcos_cm": distancia_surco_cm, "n_surcos": n_surcos,
    })
if st.session_state["mediciones"]:
    dfm = pd.DataFrame(st.session_state["mediciones"])
    prom = dfm.groupby("lote").agg(fotos=("pl_ha", "size"),
                                   pl_m=("pl_m", "mean"), pl_ha=("pl_ha", "mean"),
                                   media_cm=("media_cm", "mean"), desvio_cm=("desvio_cm", "mean")).reset_index()
    prom.insert(2, "m_surco", [round((dfm[dfm.lote == l].largo_cm * dfm[dfm.lote == l].n_surcos).sum() / 100, 1)
                       for l in prom.lote])
    st.markdown("**Promedio por lote**")
    st.dataframe(prom.round(2), hide_index=True)
    if (prom.m_surco < 10).any():
        st.caption("SIMA recomienda cerca de 10 m de surco por punto de muestreo: con menos, el promedio es poco representativo.")
    st.markdown("**Todas las fotos**")
    st.dataframe(dfm, hide_index=True)
    st.download_button("Descargar CSV", dfm.to_csv(index=False).encode("utf-8"), "stand_plantas.csv", "text/csv")
    st.caption("Las mediciones viven en esta sesión del navegador: descargá el CSV antes de cerrar la página.")
