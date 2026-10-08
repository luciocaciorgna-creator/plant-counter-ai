"""Almacenamiento de establecimientos, lotes y muestras (fotos + resultados).

Se guarda en la carpeta data/ junto a la app:

    data/estructura.json                      establecimientos -> lotes -> configuración
    data/ultimo.json                          último establecimiento y lote que se usó
    data/muestras/<est>/<lote>/<id>/foto.jpg  foto de la muestra (máx. 1400 px de ancho)
    data/muestras/<est>/<lote>/<id>/meta.json correcciones y parámetros

PERMANENCIA: en Streamlit Cloud el disco se borra cuando la app se reinicia o se vuelve a
desplegar. Para que lo guardado no se pierda, se puede conectar un repositorio PRIVADO de
GitHub (ver "secrets" en el README o en la barra lateral de la app). Con eso:
  - cada cambio se sube al repositorio apenas se guarda;
  - al arrancar, lo que falte en el disco se baja del repositorio.
Sin configuración, funciona igual pero solo en el disco local (temporal).
"""
import base64
import hashlib
import io
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

import cv2
import numpy as np

ROOT = Path("data")
CFG_DEFAULT = {"entre_surcos": 52.5, "n_surcos": 2, "objetivo": 0}

_PULLED = False
_ERRORES = []
_ENVIADOS = {}  # ruta remota -> hash del último contenido subido


# ================================================================ GitHub (opcional)
class _GitHub:
    def __init__(self, token, repo, branch="main", api="https://api.github.com"):
        self.token, self.repo, self.branch, self.api = token, repo, branch, api.rstrip("/")

    def _h(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}

    def _url(self, path):
        return f"{self.api}/repos/{self.repo}/contents/{quote(path)}"

    def _sha(self, path):
        import requests
        r = requests.get(self._url(path), headers=self._h(), params={"ref": self.branch}, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("sha")

    def put(self, path, datos, mensaje):
        import requests
        for intento in range(2):
            body = {"message": mensaje, "content": base64.b64encode(datos).decode(), "branch": self.branch}
            sha = self._sha(path)
            if sha:
                body["sha"] = sha
            r = requests.put(self._url(path), headers=self._h(), json=body, timeout=60)
            if r.status_code in (409, 422) and intento == 0:
                time.sleep(0.6)
                continue
            r.raise_for_status()
            return

    def delete(self, path, mensaje):
        import requests
        sha = self._sha(path)
        if not sha:
            return
        r = requests.delete(self._url(path), headers=self._h(), timeout=30,
                            json={"message": mensaje, "sha": sha, "branch": self.branch})
        r.raise_for_status()

    def bajar_todo(self):
        """Devuelve {ruta_relativa_a_data: bytes} con todo lo que hay en data/ del repositorio."""
        import requests
        r = requests.get(f"{self.api}/repos/{self.repo}/zipball/{self.branch}", headers=self._h(), timeout=120)
        if r.status_code in (404, 409):  # repositorio vacío
            return {}
        r.raise_for_status()
        out = {}
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for n in z.namelist():
                partes = n.split("/", 1)
                if len(partes) == 2 and partes[1].startswith("data/") and not n.endswith("/"):
                    out[partes[1][len("data/"):]] = z.read(n)
        return out


def _remoto():
    token = os.environ.get("GH_TOKEN")
    repo = os.environ.get("GH_REPO")
    branch = os.environ.get("GH_BRANCH", "main")
    api = os.environ.get("GH_API", "https://api.github.com")
    if not (token and repo):
        try:
            import streamlit as st
            g = st.secrets["github"]
            token, repo = g["token"], g["repo"]
            branch = g.get("branch", "main")
            api = g.get("api_url", api)
        except Exception:
            return None
    return _GitHub(token, repo, branch, api)


def estado_almacenamiento():
    gh = _remoto()
    return {"modo": "github" if gh else "local", "repo": gh.repo if gh else None}


def ultimo_error():
    return _ERRORES[-1] if _ERRORES else None


def _registrar(e, accion):
    msg = f"{accion}: {type(e).__name__}: {str(e)[:200]}"
    _ERRORES.append(msg)


def _rel(ruta):
    return Path(ruta).resolve().relative_to(ROOT.resolve()).as_posix()


def _push(ruta, datos=None):
    gh = _remoto()
    if not gh:
        return
    try:
        rel = "data/" + _rel(ruta)
        datos = Path(ruta).read_bytes() if datos is None else datos
        h = hashlib.sha256(datos).hexdigest()
        if _ENVIADOS.get(rel) == h:
            return
        gh.put(rel, datos, f"Plant Counter: {rel}")
        _ENVIADOS[rel] = h
    except Exception as e:
        _registrar(e, "No pude subir a GitHub")


def _push_delete(rutas_rel):
    gh = _remoto()
    if not gh:
        return
    for rel in rutas_rel:
        try:
            gh.delete("data/" + rel, f"Plant Counter: eliminar {rel}")
            _ENVIADOS.pop("data/" + rel, None)
        except Exception as e:
            _registrar(e, "No pude borrar en GitHub")


def sincronizar_inicio(forzar=False):
    """Una vez por arranque: baja de GitHub lo que falte en el disco. Devuelve cuántos archivos trajo."""
    global _PULLED
    if _PULLED and not forzar:
        return 0
    _PULLED = True
    gh = _remoto()
    if not gh:
        return 0
    try:
        traidos = 0
        for rel, datos in gh.bajar_todo().items():
            destino = ROOT / rel
            if forzar or not destino.exists():
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(datos)
                _ENVIADOS["data/" + rel] = hashlib.sha256(datos).hexdigest()
                traidos += 1
            else:
                _ENVIADOS.setdefault("data/" + rel, hashlib.sha256(destino.read_bytes()).hexdigest())
        return traidos
    except Exception as e:
        _registrar(e, "No pude bajar de GitHub")
        return 0


def subir_todo():
    """Sube a GitHub todo lo que hay en el disco (útil la primera vez). Devuelve cuántos archivos."""
    n = 0
    if ROOT.exists():
        for p in sorted(ROOT.rglob("*")):
            if p.is_file():
                _push(p)
                n += 1
    return n


# ===================================================================== utilidades
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
    _push(ruta)


# ===================================================================== estructura
def cargar_estructura():
    sincronizar_inicio()  # antes de leer: si el disco está vacío, trae lo guardado en GitHub
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


def listar_contratistas():
    sincronizar_inicio()
    return sorted({str(c) for c in _leer_json(ROOT / "contratistas.json", [])}, key=str.lower)


def agregar_contratista(nombre):
    nombre = " ".join(nombre.split())
    actuales = listar_contratistas()
    if not nombre or nombre.lower() in (c.lower() for c in actuales):
        return False
    _escribir_json(ROOT / "contratistas.json", sorted(actuales + [nombre], key=str.lower))
    return True


def leer_ultimo():
    return _leer_json(ROOT / "ultimo.json", {})


def guardar_ultimo(establecimiento, lote):
    if leer_ultimo() != {"est": establecimiento, "lote": lote}:
        _escribir_json(ROOT / "ultimo.json", {"est": establecimiento, "lote": lote})


# ======================================================================== muestras
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
    foto = comprimir(datos)
    (carpeta / "foto.jpg").write_bytes(foto)
    _push(carpeta / "foto.jpg", foto)
    meta = {**meta, "creada": time.time()}
    _escribir_json(carpeta / "meta.json", meta)
    return muestra_id


def actualizar_muestra(establecimiento, lote, muestra_id, meta):
    carpeta = _carpeta_lote(establecimiento, lote) / muestra_id
    actual = _leer_json(carpeta / "meta.json", {})
    meta = {k: v for k, v in meta.items() if k != "id"}
    _escribir_json(carpeta / "meta.json", {**actual, **meta, "creada": actual.get("creada", time.time())})


def eliminar_muestra(establecimiento, lote, muestra_id):
    carpeta = _carpeta_lote(establecimiento, lote) / muestra_id
    rels = [_rel(p) for p in carpeta.rglob("*") if p.is_file()] if carpeta.exists() else []
    shutil.rmtree(carpeta, ignore_errors=True)
    _push_delete(rels)


# ========================================================================== respaldo
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
            _push(destino)
    return True
