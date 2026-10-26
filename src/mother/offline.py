"""Paquete offline para laboratorios sin red (Ola 11): `empaquetar-offline` e `instalar --desde-archivo`.

`mother empaquetar-offline --perfil estudiante` arma, en una máquina con red, un `.tar.gz` con las
ruedas (wheels) de cada herramienta del perfil y de todas sus dependencias, los zipapps
(`mother.pyz` y, si el perfil tiene ripley, `ripley.pyz` verificado contra el SHA256SUMS de su
release) y `paquete.json`: qué herramientas trae, para qué Python y plataforma se armó y la suma
SHA-256 de cada archivo. `mother instalar --desde-archivo paquete.tar.gz` lo instala sin red:
verifica cada suma (un archivo alterado cancela todo), y llama a `uv tool install --offline
--no-index` con las ruedas del paquete.

Las dependencias entre herramientas son referencias git (`yutani @ git+https://…`, N-ECO-01): sin
red uv no puede seguirlas, así que cada instalación lleva un archivo de `--overrides` que reemplaza
cada dependencia por su rueda local. Las ruedas se arman por herramienta (cada una en su entorno, con
sus propias fijaciones); las idénticas se guardan una sola vez.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipapp
from importlib import resources
from pathlib import Path

from mother import __version__
from mother.manifiesto import Repo

ESQUEMA_PAQUETE = "1.0.0"
URL_RIPLEY = "https://github.com/INGCOM-UNRN-P1/ripley/releases/{}/ripley.pyz"


class ErrorDePaquete(Exception):
    """El paquete no se pudo armar o no se puede instalar (alterado, de otra plataforma…)."""


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _distribucion(rueda: Path) -> str:
    """`pyyaml-6.0.3-cp312-….whl` → `pyyaml` (el nombre normalizado del archivo de la rueda)."""
    return rueda.name.split("-", 1)[0].lower()


def version_python() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


# ── empaquetar ───────────────────────────────────────────────────────────────────────────────

def _ruedas(repo: Repo, python: str, destino: Path) -> list[Path]:
    """Ruedas de `repo` y de todas sus dependencias (pip wheel resuelve también las referencias git)."""
    destino.mkdir(parents=True, exist_ok=True)
    comando = ["uv", "tool", "run", "--python", python, "--from", "pip", "pip", "wheel", "--quiet",
               "--wheel-dir", str(destino), repo.requisito_git()]
    print("$ " + " ".join(comando), flush=True)
    res = subprocess.run(comando, capture_output=True, text=True)
    if res.returncode != 0:
        raise ErrorDePaquete(f"no se pudieron armar las ruedas de {repo.nombre}:\n{(res.stderr or res.stdout)[-2000:]}")
    return sorted(destino.glob("*.whl"))


def _mother_pyz(destino: Path) -> Path:
    """El zipapp de mother: el que está corriendo, o uno nuevo con el paquete instalado."""
    paquete = Path(__file__).resolve().parent
    if paquete.parent.suffix == ".pyz" and paquete.parent.is_file():
        shutil.copyfile(paquete.parent, destino)
        return destino
    with tempfile.TemporaryDirectory() as tmp:
        fuente = Path(tmp) / "app"
        shutil.copytree(Path(str(resources.files("mother"))), fuente / "mother",
                        ignore=shutil.ignore_patterns("__pycache__"))
        zipapp.create_archive(fuente, destino, interpreter="/usr/bin/env python3", main="mother.cli:_principal")
    return destino


def _descargar(url: str, destino: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as respuesta:  # noqa: S310 (URL fija de los releases)
        destino.write_bytes(respuesta.read())


def descargar_verificado(url: str, destino: Path) -> None:
    """Descarga `url` y la verifica contra el SHA256SUMS del mismo release; si no coincide, falla."""
    nombre = url.rsplit("/", 1)[1]
    _descargar(url, destino)
    sumas = destino.with_name(destino.name + ".SHA256SUMS")
    try:
        _descargar(url.rsplit("/", 1)[0] + "/SHA256SUMS", sumas)
        esperadas = {partes[1].lstrip("*"): partes[0].lower() for partes in
                     (linea.split() for linea in sumas.read_text(encoding="utf-8").splitlines()) if len(partes) == 2}
    finally:
        sumas.unlink(missing_ok=True)
    if nombre not in esperadas:
        destino.unlink(missing_ok=True)
        raise ErrorDePaquete(f"el SHA256SUMS del release no trae la suma de {nombre}")
    real = sha256(destino)
    if real != esperadas[nombre]:
        destino.unlink(missing_ok=True)
        raise ErrorDePaquete(f"la suma SHA-256 de {nombre} no coincide con la del release "
                             f"(esperada {esperadas[nombre]}, descargada {real})")


def empaquetar(repos: list[Repo], salida: Path, *, perfiles: list[str], cuatrimestre: str | None,
               python: str, zipapps: bool = True) -> dict:
    """Arma el paquete en `salida` y devuelve su `paquete.json`."""
    if shutil.which("uv") is None:
        raise ErrorDePaquete("hace falta uv (y red) para armar el paquete")
    with tempfile.TemporaryDirectory(prefix="mother-paquete-") as tmp:
        raiz = Path(tmp) / "paquete"
        pool = raiz / "ruedas"
        pool.mkdir(parents=True)
        herramientas = []
        for repo in repos:
            rutas = []
            for rueda in _ruedas(repo, python, Path(tmp) / "armado" / repo.nombre):
                destino = pool / rueda.name
                if destino.exists() and sha256(destino) != sha256(rueda):
                    destino = pool / repo.nombre / rueda.name  # mismo nombre, otro contenido (otra fijación)
                    destino.parent.mkdir(exist_ok=True)
                if not destino.exists():
                    shutil.copyfile(rueda, destino)
                rutas.append(destino.relative_to(raiz).as_posix())
            propia = next((r for r in rutas if _distribucion(Path(r)) == repo.paquete.lower().replace("-", "_")), None)
            if propia is None:
                raise ErrorDePaquete(f"entre las ruedas de {repo.nombre} no está la del paquete {repo.paquete}")
            herramientas.append({"nombre": repo.nombre, "paquete": repo.paquete, "extras": repo.extras,
                                 "ejecutables": repo.ejecutables, "ref": repo.ref, "rueda": propia, "ruedas": rutas})
        lista_zipapps = []
        if zipapps:
            (raiz / "zipapps").mkdir()
            _mother_pyz(raiz / "zipapps" / "mother.pyz")
            lista_zipapps.append("zipapps/mother.pyz")
            ripley = next((r for r in repos if r.nombre == "ripley"), None)
            if ripley is not None:
                donde = f"download/{ripley.ref}" if ripley.ref.startswith("v") else "latest/download"
                try:
                    descargar_verificado(URL_RIPLEY.format(donde), raiz / "zipapps" / "ripley.pyz")
                    lista_zipapps.append("zipapps/ripley.pyz")
                except (urllib.error.URLError, OSError) as error:
                    print(f"· sin ripley.pyz en el paquete (no se pudo descargar: {error})", file=sys.stderr)
        archivos = {p.relative_to(raiz).as_posix(): sha256(p) for p in sorted(raiz.rglob("*")) if p.is_file()}
        datos = {
            "schema_version": ESQUEMA_PAQUETE,
            "creado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "mother": __version__,
            "perfiles": perfiles,
            "cuatrimestre": cuatrimestre,
            "python": python,
            "plataforma": sysconfig.get_platform(),
            "herramientas": herramientas,
            "zipapps": lista_zipapps,
            "archivos": archivos,
        }
        (raiz / "paquete.json").write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        salida.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(salida, "w:gz") as tar:
            tar.add(raiz, arcname="paquete")
    return datos


# ── instalar desde el archivo ────────────────────────────────────────────────────────────────

def _extraer(archivo: Path, destino: Path) -> Path:
    try:
        return _extraer_tar(archivo, destino)
    except (tarfile.TarError, EOFError, OSError) as error:
        raise ErrorDePaquete(f"{archivo} no es un .tar.gz legible ({error})") from None


def _extraer_tar(archivo: Path, destino: Path) -> Path:
    with tarfile.open(archivo, "r:gz") as tar:
        for miembro in tar.getmembers():
            nombre = Path(miembro.name)
            if nombre.is_absolute() or ".." in nombre.parts or not (miembro.isfile() or miembro.isdir()):
                raise ErrorDePaquete(f"el paquete trae una entrada no permitida: {miembro.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(destino, filter="data")
        else:  # pragma: no cover (Python 3.11 sin el filtro retroportado)
            tar.extractall(destino)  # noqa: S202 (miembros ya validados arriba)
    raiz = destino / "paquete"
    if not (raiz / "paquete.json").is_file():
        raise ErrorDePaquete(f"{archivo} no es un paquete de mother (falta paquete.json)")
    return raiz


def verificar(raiz: Path) -> dict:
    """Lee `paquete.json` y comprueba la suma de cada archivo (y que no sobre ni falte ninguno)."""
    datos = json.loads((raiz / "paquete.json").read_text(encoding="utf-8"))
    presentes = {p.relative_to(raiz).as_posix() for p in raiz.rglob("*") if p.is_file()} - {"paquete.json"}
    esperados = set(datos.get("archivos", {}))
    if presentes != esperados:
        sobran, faltan = sorted(presentes - esperados), sorted(esperados - presentes)
        raise ErrorDePaquete(f"el paquete no coincide con su lista de archivos (sobran: {sobran or 'nada'}; "
                             f"faltan: {faltan or 'nada'})")
    alterados = [r for r, suma in datos["archivos"].items() if sha256(raiz / r) != suma]
    if alterados:
        raise ErrorDePaquete("el paquete está alterado: la suma SHA-256 no coincide en " + ", ".join(alterados))
    return datos


def comando_instalacion(herramienta: dict, raiz: Path, python: str, overrides: Path, forzar: bool) -> list[str]:
    rueda = (raiz / herramienta["rueda"]).resolve()
    extras = f"[{','.join(herramienta['extras'])}]" if herramienta.get("extras") else ""
    comando = ["uv", "tool", "install", "--offline", "--no-index", "--find-links", str((raiz / "ruedas").resolve()),
               "--overrides", str(overrides), "--python", python]
    if forzar:
        comando.append("--force")
    return comando + [f"{herramienta['paquete']}{extras} @ {rueda.as_uri()}"]


def instalar_desde_archivo(archivo: Path, *, forzar: bool = False, simular: bool = False,
                           binarios: Path | None = None) -> int:
    with tempfile.TemporaryDirectory(prefix="mother-offline-") as tmp:
        raiz = _extraer(archivo, Path(tmp))
        datos = verificar(raiz)
        print(f"✓ Paquete íntegro: {len(datos['archivos'])} archivos con su suma SHA-256 "
              f"(perfil {', '.join(datos.get('perfiles') or ['?'])}, armado el {datos.get('creado', '?')}).")
        plataforma = sysconfig.get_platform()
        if datos.get("plataforma") != plataforma:
            raise ErrorDePaquete(f"el paquete es para {datos.get('plataforma')} y esta máquina es {plataforma}: "
                                 f"armalo en una máquina como las del laboratorio")
        if not simular and shutil.which("uv") is None:
            raise ErrorDePaquete("hace falta uv para instalar (en el entorno de la cátedra viene incluido)")
        fallidas = []
        for herramienta in datos["herramientas"]:
            overrides = Path(tmp) / f"overrides-{herramienta['nombre']}.txt"
            overrides.write_text("".join(f"{_distribucion(Path(r))} @ {(raiz / r).resolve().as_uri()}\n"
                                         for r in herramienta["ruedas"]), encoding="utf-8")
            comando = comando_instalacion(herramienta, raiz, datos["python"], overrides, forzar)
            print("$ " + " ".join(f'"{c}"' if " " in c else c for c in comando), flush=True)
            if not simular and subprocess.run(comando).returncode != 0:
                fallidas.append(herramienta["nombre"])
        if datos.get("zipapps") and binarios is not None:
            for zipapp_rel in datos["zipapps"]:
                destino = binarios / Path(zipapp_rel).name
                print(f"$ copiar {zipapp_rel} → {destino}", flush=True)
                if not simular:
                    binarios.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(raiz / zipapp_rel, destino)
                    destino.chmod(0o755)
    if fallidas:
        print(f"\nNo se pudieron instalar: {', '.join(fallidas)}. ¿Está Python {datos['python']} en esta máquina? "
              f"(uv sin red no lo puede descargar)", file=sys.stderr)
        return 1
    return 0


def tamanio(ruta: Path) -> str:
    return f"{os.path.getsize(ruta) / 1048576:.1f} MiB"
