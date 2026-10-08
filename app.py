import hashlib
import math
import time

import cv2
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image

import plant_logic as pl
import reporte as rp
import storage as sto
import viewer as vw

st.set_page_config(page_title="Plant Counter AI V1.2", layout="wide")
st.title("🌱 Plant Counter AI")
st.subheader("Stand de plantas")

sb = st.sidebar


def etq(a):
    return "Sin asignar" if not a else f"Ambiente {a}"


def _cambiar_amb(est_, lote_, sid, key):
    sto.actualizar_muestra(est_, lote_, sid, {"ambiente": int(st.session_state[key])})


# Al arrancar (o después de un reinicio de Streamlit Cloud) trae lo guardado en GitHub, si está configurado.
with st.spinner("Cargando datos guardados..."):
    sto.sincronizar_inicio()

# ============================================================ establecimiento / lote
sb.header("🏢 Establecimiento y lote")
for k in ("sel_est", "sel_lote"):  # selección pendiente tras crear uno nuevo
    if f"_next_{k}" in st.session_state:
        st.session_state[k] = st.session_state.pop(f"_next_{k}")

estructura = sto.cargar_estructura()
ests = list(estructura.keys())
ult = sto.leer_ultimo()  # la primera vez de cada sesión, vuelve al último establecimiento y lote usados
if "sel_est" not in st.session_state and ult.get("est") in ests:
    st.session_state["sel_est"] = ult["est"]
    if ult.get("lote") in estructura[ult["est"]]:
        st.session_state["sel_lote"] = ult["lote"]
if st.session_state.get("sel_est") not in ests:
    st.session_state.pop("sel_est", None)
est = sb.selectbox("Establecimiento", ests, key="sel_est")
with sb.form("f_est", clear_on_submit=True):
    nuevo_est = st.text_input("Nuevo establecimiento")
    if st.form_submit_button("Agregar establecimiento") and sto.agregar_establecimiento(nuevo_est):
        st.session_state["_next_sel_est"] = nuevo_est.strip()
        st.rerun()

lotes = list(estructura.get(est, {}).keys())
if st.session_state.get("sel_lote") not in lotes:
    st.session_state.pop("sel_lote", None)
lote = sb.selectbox("Lote", lotes, key="sel_lote") if lotes else None
with sb.form("f_lote", clear_on_submit=True):
    nuevo_lote = st.text_input("Nuevo lote")
    if st.form_submit_button("Agregar lote") and sto.agregar_lote(est, nuevo_lote):
        st.session_state["_next_sel_lote"] = nuevo_lote.strip()
        st.rerun()

if lote is None:
    st.info("Este establecimiento todavía no tiene lotes. Agregá uno desde la barra lateral.")
    st.stop()
sto.guardar_ultimo(est, lote)

# ----------------------------------------------------- configuración (se guarda por lote)
cfg = sto.cfg_lote(est, lote)
pref = f"{est}|{lote}|"
sb.header("Datos del lote")
distancia_surco_cm = sb.number_input("Distancia entre surcos (cm)", 10.0, 150.0,
                                     float(cfg["entre_surcos"]), 0.5, key=pref + "entre")
n_surcos = int(sb.number_input("Surcos en la foto", 2, 6, int(cfg["n_surcos"]), 1, key=pref + "n"))
objetivo = sb.number_input("Densidad objetivo (pl/ha, opcional)", 0, 300000, int(cfg["objetivo"]), 1000,
                           key=pref + "obj")
tiene_amb = sb.checkbox("El lote tiene ambientes", int(cfg.get("ambientes", 1)) > 1, key=pref + "tamb",
                        help="Si lo prendés, al cargar cada foto elegís a qué ambiente pertenece y "
                             "los resultados se promedian por ambiente y en general.")
n_amb = int(sb.number_input("Cantidad de ambientes", 2, 12, max(2, int(cfg.get("ambientes", 2))), 1,
                            key=pref + "namb")) if tiene_amb else 1
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
              "inclinada": bool(inclinada), "largo_real": int(largo_real), "ambientes": n_amb}
if any(cfg.get(k) != v for k, v in cfg_actual.items()):
    sto.guardar_cfg(est, lote, cfg_actual)

# ----------------------------------------------------------------------- respaldo
_alm = sto.estado_almacenamiento()
if _alm["modo"] == "github":
    sb.success(f"💾 Guardado permanente en GitHub ({_alm['repo']})")
else:
    sb.warning("⚠️ Guardado temporal: Streamlit Cloud borra los datos cuando la app se reinicia. "
               "Conectá un repositorio de GitHub (ver abajo, en Respaldo de datos) o bajá respaldos.")
if sto.ultimo_error():
    sb.error(f"Problema con GitHub: {sto.ultimo_error()}")

with sb.expander("💾 Respaldo de datos"):
    if _alm["modo"] == "github":
        st.caption("Cada cambio se sube solo al repositorio. Estos botones sirven si algo quedó desparejo.")
        if st.button("Subir todo a GitHub", key="gh_up"):
            with st.spinner("Subiendo..."):
                n_ = sto.subir_todo()
            st.success(f"{n_} archivos revisados/subidos.")
        if st.button("Traer todo de GitHub (pisa lo local)", key="gh_down"):
            with st.spinner("Bajando..."):
                n_ = sto.sincronizar_inicio(forzar=True)
            st.success(f"{n_} archivos traídos.")
    else:
        st.markdown("**Para que no se pierdan los datos:** creá un repositorio **privado** en GitHub, un token "
                    "(*Settings → Developer settings → Fine-grained tokens*, solo ese repositorio, permiso "
                    "**Contents: Read and write**) y en Streamlit Cloud *Settings → Secrets* pegá:")
        st.code('[github]\ntoken = "github_pat_..."\nrepo = "tu_usuario/tu_repositorio"\nbranch = "main"',
                language="toml")
        st.caption("Mientras tanto, bajá un respaldo (.zip) de vez en cuando.")
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


def amb_valido(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 0
    return v if 1 <= v <= n_amb else 0


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
    if n_amb <= 1:
        amb = 0
    elif f["guardada"]:
        amb = amb_valido(f["meta"].get("ambiente", 0))
    else:
        amb = amb_valido(st.session_state.get(f"amb_{fid}", st.session_state.get("ult_amb", 1)))
    m = {**f, "amb": amb, "img": img, "h": h, "w": w, "ids": ids_validos, "qkey": qkey, "akey": akey,
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
    if n_amb > 1:
        st.caption("Elegí el ambiente de cada foto antes de guardarla.")
        for m_ in nuevas:
            ult = int(st.session_state.get("ult_amb", 1))
            v_ = st.selectbox(f"Ambiente de {m_['nombre']}", list(range(1, n_amb + 1)),
                              index=min(max(ult, 1), n_amb) - 1, format_func=etq, key=f"amb_{m_['fid']}")
            st.session_state["ult_amb"] = v_
    if st.button(f"💾 Guardar {len(nuevas)} foto(s) en {est} / {lote}", type="primary"):
        with st.spinner("Guardando..."):
            for m in nuevas:
                sto.guardar_muestra(est, lote, m["datos"], {
                    "nombre": m["nombre"], "sens": m["sens"], "quitar": m["quitar"], "ambiente": m["amb"],
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
            "Muestra": f"{k + 1}. {m['nombre']}" + ("" if m["guardada"] else " (sin guardar)"), "_amb": m["amb"],
            "Plantas": t["plantas"], "m de surco": round(t["largo_cm"] * n_surcos / 100, 1),
            "pl/m": round(t["pl_m"], 2), "pl/ha": round(t["pl_ha"]),
            "Media (cm)": round(t["media_cm"], 1), "Desvío (cm)": round(t["desvio_cm"], 1),
            "CV (%)": round(t["cv"], 1), "CV": pl.semaforo(t["cv"], 22, 30),
        })
    df_all = pd.DataFrame(filas)
    df = df_all.drop(columns="_amb")
    if n_amb > 1:
        df.insert(1, "Ambiente", [etq(a) for a in df_all["_amb"]])

    def calc_prom(d):
        p = {"pl_m": d["pl/m"].mean(), "pl_ha": d["pl/ha"].mean(), "media": d["Media (cm)"].mean(),
             "desvio": d["Desvío (cm)"].mean(), "cv": d["CV (%)"].mean(),
             "plantas": int(d["Plantas"].sum()), "metros": d["m de surco"].sum(),
             "ent_sd": d["pl/ha"].std(ddof=1) if len(d) > 1 else float("nan")}
        p["ent_cv"] = p["ent_sd"] / p["pl_ha"] * 100 if len(d) > 1 else float("nan")
        return p

    prom = calc_prom(df_all)

    if n_amb > 1:
        st.subheader("Promedio general del lote (todas las muestras)")
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

    # ------------------------------------------------------------- promedio por ambiente
    por_amb = []
    if n_amb > 1:
        presentes = set(df_all["_amb"])
        for a in list(range(1, n_amb + 1)) + [0]:
            sub = df_all[df_all["_amb"] == a]
            if sub.empty:
                continue
            pa = calc_prom(sub)
            por_amb.append({"nombre": etq(a), "n": len(sub), "plantas": pa["plantas"], "metros": pa["metros"],
                            "pl_m": pa["pl_m"], "pl_ha": pa["pl_ha"], "media": pa["media"],
                            "desvio": pa["desvio"], "cv": pa["cv"],
                            "dev": (pa["pl_ha"] - objetivo) / objetivo * 100 if objetivo > 0 else None})
        general = {"nombre": "GENERAL DEL LOTE", "n": len(df_all), "plantas": prom["plantas"],
                   "metros": prom["metros"], "pl_m": prom["pl_m"], "pl_ha": prom["pl_ha"], "media": prom["media"],
                   "desvio": prom["desvio"], "cv": prom["cv"],
                   "dev": (prom["pl_ha"] - objetivo) / objetivo * 100 if objetivo > 0 else None}
        filas_amb = []
        for p_ in por_amb + [general]:
            fa = {"Ambiente": p_["nombre"], "Muestras": p_["n"], "Plantas": p_["plantas"],
                  "m de surco": round(p_["metros"], 1), "pl/m": round(p_["pl_m"], 2), "pl/ha": round(p_["pl_ha"]),
                  "Media (cm)": round(p_["media"], 1), "Desvío (cm)": round(p_["desvio"], 1),
                  "CV (%)": round(p_["cv"], 1), "CV": pl.semaforo(p_["cv"], 22, 30)}
            if objetivo > 0:
                fa["Desv. pobl. (%)"] = round(p_["dev"], 1)
                fa["Desv."] = pl.semaforo(abs(p_["dev"]), 5, 10)
            filas_amb.append(fa)
        st.subheader("🗺️ Promedio por ambiente")
        st.dataframe(pd.DataFrame(filas_amb), hide_index=True)
        vacios = [etq(a) for a in range(1, n_amb + 1) if a not in presentes]
        if vacios:
            st.caption("Ambientes sin muestras todavía: " + ", ".join(vacios) + ".")
        if 0 in presentes:
            st.warning("Hay muestras sin ambiente asignado: elegilo en el detalle de cada muestra.")
        st.caption("Cada promedio es el promedio simple de las muestras del ambiente. El general del lote es el "
                   "promedio simple de todas las muestras (no pondera por superficie de cada ambiente).")

    fila_prom = {"Muestra": "PROMEDIO", "Plantas": prom["plantas"], "m de surco": round(prom["metros"], 1),
                 "pl/m": round(prom["pl_m"], 2), "pl/ha": round(prom["pl_ha"]),
                 "Media (cm)": round(prom["media"], 1), "Desvío (cm)": round(prom["desvio"], 1),
                 "CV (%)": round(prom["cv"], 1), "CV": pl.semaforo(prom["cv"], 22, 30)}
    if n_amb > 1:
        fila_prom["Ambiente"] = "Todos"
    st.subheader("Muestras")
    tabla = pd.concat([df, pd.DataFrame([fila_prom])], ignore_index=True)
    st.dataframe(tabla, hide_index=True)
    if len(df) > 1:
        st.caption(f"Variación de la densidad entre muestras: desvío {prom['ent_sd']:,.0f} pl/ha "
                   f"(CV {prom['ent_cv']:.1f} %). El promedio es el promedio simple de las muestras.")
    if prom["metros"] < 10:
        st.caption("SIMA recomienda cerca de 10 m de surco por punto de muestreo: con menos, "
                   "el promedio es poco representativo.")
    csv = tabla
    if por_amb:
        csv = pd.concat([tabla, pd.DataFrame([{
            "Muestra": "PROMEDIO " + p_["nombre"], "Ambiente": p_["nombre"], "Plantas": p_["plantas"],
            "m de surco": round(p_["metros"], 1), "pl/m": round(p_["pl_m"], 2), "pl/ha": round(p_["pl_ha"]),
            "Media (cm)": round(p_["media"], 1), "Desvío (cm)": round(p_["desvio"], 1),
            "CV (%)": round(p_["cv"], 1), "CV": pl.semaforo(p_["cv"], 22, 30)} for p_ in por_amb])],
            ignore_index=True)
    csv = csv.assign(Establecimiento=est, Lote=lote, Entre_surcos_cm=distancia_surco_cm)
    st.download_button("Descargar resumen (CSV)", csv.to_csv(index=False).encode("utf-8"),
                       f"stand_{lote}.csv", "text/csv")

    # ------------------------------------------------------------------ informe PDF
    st.subheader("📄 Informe en PDF")
    inc_orig = st.checkbox("Incluir también la foto original (al lado de la procesada)", False, key="pdf_orig")
    firma = (est, lote, inc_orig, float(distancia_surco_cm), n_surcos, int(objetivo), int(largo_real), n_amb,
             tuple((m["fid"], m["tot"]["plantas"], round(m["tot"]["pl_ha"]), tuple(m["quitar"]),
                    tuple(map(tuple, m["agregadas"])), m["sens"], m["guardada"], m["amb"]) for m in ok))
    if st.button("Generar PDF del lote"):
        with st.spinner("Armando el PDF..."):
            filas_pdf = [{"nombre": r["Muestra"].split(". ", 1)[-1], "plantas": r["Plantas"],
                          "metros": r["m de surco"], "pl_m": r["pl/m"], "pl_ha": r["pl/ha"],
                          "media": r["Media (cm)"], "desvio": r["Desvío (cm)"], "cv": r["CV (%)"],
                          "ambiente": etq(r["_amb"]) if n_amb > 1 else None}
                         for r in filas]
            mu_pdf = []
            for m_ in ok:
                todas_, lineas_, quit_ = m_["draw"]
                mu_pdf.append({"nombre": m_["nombre"], "fecha": (m_["meta"] or {}).get("fecha"), "tot": m_["tot"],
                               "surcos": m_["surcos"], "sens": m_["sens"], "orig": m_["img"],
                               "ambiente": etq(m_["amb"]) if n_amb > 1 else None,
                               "proc": pl.dibujar(m_["img"], todas_, lineas_, m_["surcos"], quit_)})
            prom_pdf = {**prom, "pl_m": float(prom["pl_m"]), "pl_ha": float(prom["pl_ha"])}
            st.session_state["pdf"] = (firma, rp.generar_pdf(
                est, lote, {"entre_surcos": float(distancia_surco_cm), "n_surcos": n_surcos,
                            "objetivo": int(objetivo), "largo_real": int(largo_real)},
                filas_pdf, prom_pdf, mu_pdf, inc_orig, por_ambiente=(por_amb + [general]) if por_amb else None))
    if "pdf" in st.session_state:
        firma_pdf, pdf_bytes = st.session_state["pdf"]
        if firma_pdf == firma:
            st.download_button("⬇️ Descargar PDF", pdf_bytes, f"stand_{est}_{lote}.pdf".replace(" ", "_"),
                               "application/pdf")
        else:
            st.caption("Cambiaron las muestras o los datos desde el último PDF: volvé a generarlo.")

# ============================================================== detalle por muestra
st.header("🔍 Detalle por muestra")
fids = [m["fid"] for m in muestras]
nombres = {m["fid"]: f"{k + 1}. {m['nombre']}" + (f" · {etq(m['amb'])}" if n_amb > 1 else "")
           + ("" if m["guardada"] else " (sin guardar)") for k, m in enumerate(muestras)}
skey = f"selm_{est}_{lote}"
if st.session_state.get(skey) not in fids:
    st.session_state.pop(skey, None)
fid_sel = st.selectbox("Elegí la muestra", fids, format_func=lambda f: nombres[f], key=skey)
m = muestras[fids.index(fid_sel)]
fid = m["fid"]
if n_amb > 1:
    if m["guardada"]:
        kamb = f"ambsel_{fid}"
        opciones_amb = list(range(0, n_amb + 1))
        if st.session_state.get(kamb) not in opciones_amb:
            st.session_state[kamb] = m["amb"]
        st.selectbox("Ambiente de esta muestra", opciones_amb, format_func=etq, key=kamb,
                     on_change=_cambiar_amb, args=(est, lote, m["sid"], kamb))
    else:
        st.caption(f"{etq(m['amb'])} (se elige arriba, antes de guardar la foto).")
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
