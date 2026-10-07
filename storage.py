"""Almacenamiento de establecimientos, lotes y muestras (fotos + resultados).

Todo se guarda en la carpeta data/ junto a la app:

    data/estructura.json                      establecimientos -> lotes -> configuración
    data/muestras/<est>/<lote>/<id>/foto.jpg  foto de la muestra (máx. 1400 px de ancho)
    data/muestras/<est>/<lote>/<id>/meta.json correcciones, parámetros y resultados

OJO: en Streamlit Community Cloud el disco NO es permanente. Se borra cuando la app
se reinicia o se vuelve a desplegar. Por eso hay exportar_zip() / importar_zip()
para hacer un respaldo y restaurarlo.
"""
import hashlib
import io
import json
import re
import shutil
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path("data")
CFG_DEFAULT = {"entre_surcos": 52.0, "n_surcos": 2, "objetivo": 0}


def _slug(nombre):
    base = re.sub(r"[^a-zA-Z0-9]+", "_", nombre).strip("_").lower() or "x"
    return f"{base[:40]}-{hashlib.md5(nombre.encode()).hexdigest()[:6]}"


def _leer_json(ruta, defecto):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _escribir_json(ruta, datos):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)


# ------------------------------------------------------------- estructura
def cargar_estructura():
    est = _leer_json(ROOT / "estructura.json", None)
    if not est:
        est = {"Establecimiento 1": {"Lote 1": dict(CFG_DEFAULT)}}
        _escribir_json(ROOT / "estructura.json", est)
    return est


def agregar_establecimiento(nombre):
    nombre = nombre.strip()
    est = cargar_estructura()
    if not nombre or nombre in est:
        return False
    est[nombre] = {}
    _escribir_json(ROOT / "estructura.json", est)
    return True


def agregar_lote(establecimiento, nombre):
    nombre = nombre.strip()
    est = cargar_estructura()
    if not nombre or establecimiento not in est or nombre in est[establecimiento]:
        return False
    est[establecimiento][nombre] = dict(CFG_DEFAULT)
    _escribir_json(ROOT / "estructura.json", est)
    return True


def guardar_cfg(establecimiento, lote, cfg):
    est = cargar_estructura()
    est[establecimiento][lote] = cfg
    _escribir_json(ROOT / "estructura.json", est)


def cfg_lote(establecimiento, lote):
    est = cargar_estructura()
    return {**CFG_DEFAULT, **est.get(establecimiento, {}).get(lote, {})}


# --------------------------------------------------------------- muestras
def _carpeta_lote(establecimiento, lote):
    return ROOT / "muestras" / _slug(establecimiento) / _slug(lote)


def listar_muestras(establecimiento, lote):
    out = []
    base = _carpeta_lote(establecimiento, lote)
    if not base.exists():
        return out
    for d in base.iterdir():
        meta = _leer_json(d / "meta.json", None)
        if meta and (d / "foto.jpg").exists():
            meta["id"] = d.name
            out.append(meta)
    out.sort(key=lambda m: m.get("creada", 0))
    return out


def leer_foto(establecimiento, lote, muestra_id):
    return (_carpeta_lote(establecimiento, lote) / muestra_id / "foto.jpg").read_bytes()


def comprimir(datos, ancho_max=1400):
    img = cv2.imdecode(np.frombuffer(datos, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    if w > ancho_max:
        img = cv2.resize(img, (ancho_max, int(h * ancho_max / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buf.tobytes()


def guardar_muestra(establecimiento, lote, datos, meta):
    muestra_id = f"{int(time.time() * 1000)}"
    carpeta = _carpeta_lote(establecimiento, lote) / muestra_id
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "foto.jpg").write_bytes(comprimir(datos))
    meta = {**meta, "creada": time.time()}
    _escribir_json(carpeta / "meta.json", meta)
    return muestra_id


def actualizar_muestra(establecimiento, lote, muestra_id, meta):
    carpeta = _carpeta_lote(establecimiento, lote) / muestra_id
    actual = _leer_json(carpeta / "meta.json", {})
    meta = {k: v for k, v in meta.items() if k != "id"}
    _escribir_json(carpeta / "meta.json", {**actual, **meta, "creada": actual.get("creada", time.time())})


def eliminar_muestra(establecimiento, lote, muestra_id):
    shutil.rmtree(_carpeta_lote(establecimiento, lote) / muestra_id, ignore_errors=True)


# ---------------------------------------------------------------- respaldo
def exportar_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if ROOT.exists():
            for p in ROOT.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(ROOT).as_posix())
    return buf.getvalue()


def importar_zip(datos):
    """Restaura un respaldo. Suma lo que falte y reemplaza lo que coincide."""
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        for nombre in z.namelist():
            destino = (ROOT / nombre).resolve()
            if ROOT.resolve() not in destino.parents and destino != ROOT.resolve():
                continue  # evita rutas raras
            if nombre.endswith("/"):
                continue
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(z.read(nombre))
    return True
