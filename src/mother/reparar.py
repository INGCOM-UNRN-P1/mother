"""`mother doctor --fix`: shims huérfanos, permisos y enlaces de las herramientas (Ola 11, QoL #182).

uv instala cada herramienta en su propio entorno (`uv tool dir`, uno por paquete) y deja en el
directorio de ejecutables (`uv tool dir --bin`, casi siempre `~/.local/bin`) un enlace a cada
comando (en Windows, una copia del `.exe`). Tres cosas que un estudiante no sabe arreglar y que
`doctor` sólo veía como «no instalada» o «doctor --json no devolvió JSON»:

- **shims huérfanos**: el entorno de la herramienta se borró (o se desinstaló a mano) y el comando
  quedó apuntando a nada; en la terminal da un «No such file or directory» que confunde;
- **permisos**: el ejecutable del entorno perdió el bit de ejecución (copias entre discos, un
  `chmod -R` de más, un zip): «Permission denied»;
- **enlaces faltantes**: el entorno está pero el comando no (se borró `~/.local/bin/hal`, o se
  instaló con otro `UV_TOOL_BIN_DIR`); se rehace sin red, enlazando al ejecutable del entorno.

Sólo se tocan enlaces que apuntan al directorio de herramientas de uv y comandos del manifiesto:
nunca otros archivos de `~/.local/bin`.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from mother.manifiesto import Repo

ES_WINDOWS = os.name == "nt"


@dataclass
class Reparacion:
    accion: str  # quitar-shim-huerfano | permiso-de-ejecucion | rehacer-enlace
    objetivo: str
    detalle: str
    fuente: str = ""  # en rehacer-enlace, el ejecutable del entorno al que se enlaza
    hecha: bool | None = None  # None: sin aplicar (simulación o sólo diagnóstico)
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def directorios_uv() -> tuple[Path | None, Path | None]:
    """(directorio de entornos, directorio de ejecutables) según `uv tool dir`, o None sin uv."""
    uv = shutil.which("uv")
    if uv is None:
        return None, None
    rutas = []
    for extra in ([], ["--bin"]):
        try:
            res = subprocess.run([uv, "tool", "dir", *extra], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None, None
        rutas.append(Path(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else None)
    return rutas[0], rutas[1]


def _nombre_comando(ejecutable: str) -> str:
    return ejecutable + ".exe" if ES_WINDOWS else ejecutable


def _ejecutable_del_entorno(entornos: Path, repo: Repo, ejecutable: str) -> Path:
    carpeta = "Scripts" if ES_WINDOWS else "bin"
    return entornos / repo.paquete / carpeta / _nombre_comando(ejecutable)


def _apunta_a(enlace: Path) -> Path:
    destino = Path(os.readlink(enlace))
    return destino if destino.is_absolute() else enlace.parent / destino


def _dentro_de(ruta: Path, base: Path) -> bool:
    try:
        Path(os.path.normpath(ruta)).relative_to(Path(os.path.normpath(base)))
        return True
    except ValueError:
        return False


def diagnosticar(repos: list[Repo], entornos: Path, binarios: Path) -> list[Reparacion]:
    """Lo que hay que reparar, sin tocar nada."""
    reparaciones: list[Reparacion] = []
    vistos: set[str] = set()
    # 1. Enlaces rotos hacia el directorio de herramientas de uv (de cualquier herramienta, también
    #    de una que ya no está en el manifiesto).
    if binarios.is_dir():
        for entrada in sorted(binarios.iterdir()):
            if entrada.is_symlink() and not entrada.exists() and _dentro_de(_apunta_a(entrada), entornos):
                vistos.add(entrada.name)
                reparaciones.append(Reparacion("quitar-shim-huerfano", str(entrada),
                                               f"apunta a {_apunta_a(entrada)}, que ya no existe"))
    for repo in repos:
        entorno = entornos / repo.paquete
        for ejecutable in repo.ejecutables:
            comando = binarios / _nombre_comando(ejecutable)
            if comando.name in vistos:
                continue
            real = _ejecutable_del_entorno(entornos, repo, ejecutable)
            existe_comando = comando.exists() or comando.is_symlink()
            if existe_comando and not entorno.is_dir():
                # En Windows el comando es una copia: huérfana si su entorno ya no está.
                if not comando.is_symlink():
                    reparaciones.append(Reparacion("quitar-shim-huerfano", str(comando),
                                                   f"el entorno de {repo.paquete} ({entorno}) ya no existe"))
                continue
            if not entorno.is_dir() or not real.is_file():
                continue  # no instalada: eso lo dice el doctor («mother instalar --perfil …»)
            if not existe_comando:
                reparaciones.append(Reparacion("rehacer-enlace", str(comando),
                                               f"{repo.nombre} está instalada pero falta el comando", fuente=str(real)))
            if not ES_WINDOWS and not os.access(real, os.X_OK):
                reparaciones.append(Reparacion("permiso-de-ejecucion", str(real),
                                               f"el ejecutable de {repo.nombre} no tiene permiso de ejecución"))
    return reparaciones


def aplicar(reparaciones: list[Reparacion]) -> None:
    for r in reparaciones:
        objetivo = Path(r.objetivo)
        try:
            if r.accion == "quitar-shim-huerfano":
                objetivo.unlink()
            elif r.accion == "permiso-de-ejecucion":
                modo = objetivo.stat().st_mode
                objetivo.chmod(modo | stat.S_IXUSR | (stat.S_IXGRP if modo & stat.S_IRGRP else 0)
                               | (stat.S_IXOTH if modo & stat.S_IROTH else 0))
            elif r.accion == "rehacer-enlace":
                real = Path(r.fuente)
                objetivo.parent.mkdir(parents=True, exist_ok=True)
                if ES_WINDOWS:
                    shutil.copy2(real, objetivo)
                else:
                    objetivo.symlink_to(real)
            r.hecha = True
        except OSError as error:
            r.hecha, r.error = False, str(error)
