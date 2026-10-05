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

# p1-tools se publica en GitHub como INGCOM-UNRN-P1/toolbox (el `url` de su entrada en el manifiesto).
URL_MANIFIESTO = "https://raw.githubusercontent.com/INGCOM-UNRN-P1/toolbox/main/ecosistema.toml"
VARIABLE_MANIFIESTO = "MOTHER_MANIFIESTO"


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
    # Matriz de versiones por cuatrimestre: [cuatrimestres."2026-2"] repo = "tag o commit". Así todos
    # los estudiantes de un cuatrimestre tienen la misma versión de cada herramienta.
    cuatrimestres: dict[str, dict[str, str]] = field(default_factory=dict)
    cuatrimestre_vigente: str = ""

    def aplicar_cuatrimestre(self, nombre: str | None) -> str | None:
        """Fija el `ref` de cada repo según la matriz del cuatrimestre (por defecto, el vigente).
        Devuelve el cuatrimestre aplicado, o None si no hay ninguno."""
        nombre = nombre or self.cuatrimestre_vigente or None
        if nombre is None:
            return None
        if nombre not in self.cuatrimestres:
            raise ManifiestoInvalido(f"cuatrimestre desconocido: {nombre} "
                                     f"(en el manifiesto: {', '.join(sorted(self.cuatrimestres)) or 'ninguno'})")
        for repo in self.repos:
            if repo.nombre in self.cuatrimestres[nombre]:
                repo.ref = self.cuatrimestres[nombre][repo.nombre]
        return nombre

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
        # Tipos y estados nuevos del manifiesto no rompen a una versión vieja de mother:
        # esos repos simplemente no son instalables (`instalable` exige cli y activo).
        errores += [f"{repo.nombre}: perfil desconocido «{p}»" for p in repo.perfiles if p not in perfiles]
        if repo.tipo == "cli" and not (repo.paquete and repo.ejecutables):
            errores.append(f"{repo.nombre}: una herramienta necesita `paquete` y `ejecutables`")
        if repo.instalable and not repo.url:
            errores.append(f"{repo.nombre}: una herramienta instalable necesita `url`")
        repos.append(repo)
    cuatrimestres = datos.get("cuatrimestres", {})
    if not isinstance(cuatrimestres, dict) or not all(isinstance(v, dict) for v in cuatrimestres.values()):
        errores.append("`cuatrimestres` tiene que ser una tabla de tablas: [cuatrimestres.\"2026-2\"] repo = \"ref\"")
        cuatrimestres = {}
    for nombre_c, matriz in cuatrimestres.items():
        errores += [f"cuatrimestre {nombre_c}: «{r}» no es un repo del manifiesto" for r in matriz if r not in nombres]
    vigente = str(datos.get("cuatrimestre_vigente", ""))
    if vigente and vigente not in cuatrimestres:
        errores.append(f"cuatrimestre_vigente = {vigente}, pero no hay [cuatrimestres.\"{vigente}\"]")
    if errores:
        raise ManifiestoInvalido(f"{origen}: manifiesto inválido:\n  " + "\n  ".join(errores))
    return Manifiesto(perfiles, repos, origen,
                      {k: {r: str(v) for r, v in m.items()} for k, m in cuatrimestres.items()}, vigente)


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
