"""Lectura del manifiesto ecosistema.toml (el mismo que usa p1-tools).

El manifiesto se busca, en orden:
  1. la ruta o URL de `--manifiesto`;
  2. la variable de entorno MOTHER_MANIFIESTO;
  3. la versión publicada en p1-tools (GitHub), que se guarda en caché;
  4. la última copia en caché, si no hay red;
  5. la copia incluida en el paquete (instantánea del momento de construirlo).
"""

from __future__ import annotations

import os
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

URL_MANIFIESTO = "https://raw.githubusercontent.com/INGCOM-UNRN-P1/p1-tools/main/ecosistema.toml"
VARIABLE_MANIFIESTO = "MOTHER_MANIFIESTO"
TIPOS = {"cli", "biblioteca", "extension-vscode", "apps-script", "contenido", "plantilla",
         "libreria-c", "ejemplo", "entorno", "documentacion", "android", "especificacion"}
ESTADOS = {"activo", "deprecado", "especificacion", "ajeno", "sin-publicar"}


class ManifiestoInvalido(Exception):
    """El manifiesto no se pudo leer o no respeta el esquema."""


@dataclass
class Repo:
    nombre: str
    tipo: str
    estado: str
    url: str = ""
    carpeta: str = ""
    paquete: str = ""
    ejecutables: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)
    perfiles: list[str] = field(default_factory=list)
    plugin_ripley: str = ""
    sistema: list[str] = field(default_factory=list)
    ref: str = ""  # tag o commit a instalar; vacío = rama por defecto

    @property
    def ruta(self) -> str:
        return self.carpeta or self.nombre

    @property
    def instalable(self) -> bool:
        return self.tipo == "cli" and self.estado == "activo"

    def requisito_git(self) -> str:
        """Lo que recibe `uv tool install`: siempre desde git, nunca por nombre en PyPI."""
        url = f"git+{self.url}" + (f"@{self.ref}" if self.ref else "")
        if self.extras:
            return f"{self.paquete}[{','.join(self.extras)}] @ {url}"
        return url

    def requisito_local(self, raiz: Path) -> str:
        ruta = raiz / self.ruta
        return f"{ruta}[{','.join(self.extras)}]" if self.extras else str(ruta)


@dataclass
class Manifiesto:
    perfiles: dict[str, str]
    repos: list[Repo]
    origen: str

    def seleccionar(self, perfiles: list[str] | None = None, solo_instalables: bool = True) -> list[Repo]:
        desconocidos = set(perfiles or []) - set(self.perfiles)
        if desconocidos:
            raise ManifiestoInvalido(
                f"perfil desconocido: {', '.join(sorted(desconocidos))} (disponibles: {', '.join(self.perfiles)})")
        return [r for r in self.repos
                if (not perfiles or set(perfiles) & set(r.perfiles)) and (r.instalable or not solo_instalables)]


def interpretar(texto: str, origen: str) -> Manifiesto:
    try:
        datos = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as error:
        raise ManifiestoInvalido(f"{origen}: no es un TOML válido ({error})") from None
    perfiles = datos.get("perfiles", {})
    repos, errores, nombres = [], [], set()
    for entrada in datos.get("repo", []):
        try:
            repo = Repo(**entrada)
        except TypeError as error:
            errores.append(f"{entrada.get('nombre', '?')}: {error}")
            continue
        if repo.nombre in nombres:
            errores.append(f"{repo.nombre}: nombre repetido")
        nombres.add(repo.nombre)
        if repo.tipo not in TIPOS:
            errores.append(f"{repo.nombre}: tipo desconocido «{repo.tipo}»")
        if repo.estado not in ESTADOS:
            errores.append(f"{repo.nombre}: estado desconocido «{repo.estado}»")
        errores += [f"{repo.nombre}: perfil desconocido «{p}»" for p in repo.perfiles if p not in perfiles]
        if repo.tipo == "cli" and not (repo.paquete and repo.ejecutables):
            errores.append(f"{repo.nombre}: una herramienta necesita `paquete` y `ejecutables`")
        if repo.instalable and not repo.url:
            errores.append(f"{repo.nombre}: una herramienta instalable necesita `url`")
        repos.append(repo)
    if errores:
        raise ManifiestoInvalido(f"{origen}: manifiesto inválido:\n  " + "\n  ".join(errores))
    return Manifiesto(perfiles, repos, origen)


def _cache() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "mother" / "ecosistema.toml"


def _descargar(url: str, timeout: float = 10.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as respuesta:  # noqa: S310 (URL fija o elegida por el usuario)
        return respuesta.read().decode("utf-8")


def cargar(fuente: str | None = None, *, usar_red: bool = True) -> Manifiesto:
    """Carga el manifiesto según el orden de búsqueda documentado en el módulo."""
    fuente = fuente or os.environ.get(VARIABLE_MANIFIESTO)
    if fuente:
        if fuente.startswith(("http://", "https://")):
            try:
                return interpretar(_descargar(fuente), fuente)
            except (urllib.error.URLError, OSError) as error:
                raise ManifiestoInvalido(f"no se pudo descargar {fuente}: {error}") from None
        ruta = Path(fuente)
        if not ruta.is_file():
            raise ManifiestoInvalido(f"no existe el manifiesto {ruta}")
        return interpretar(ruta.read_text(encoding="utf-8"), str(ruta))

    cache = _cache()
    if usar_red:
        try:
            texto = _descargar(URL_MANIFIESTO)
            manifiesto = interpretar(texto, URL_MANIFIESTO)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(texto, encoding="utf-8")
            return manifiesto
        except (urllib.error.URLError, OSError, ManifiestoInvalido):
            pass
    if cache.is_file():
        return interpretar(cache.read_text(encoding="utf-8"), f"{cache} (copia en caché)")
    incluido = resources.files("mother").joinpath("ecosistema.toml")
    return interpretar(incluido.read_text(encoding="utf-8"), "copia incluida en mother")
