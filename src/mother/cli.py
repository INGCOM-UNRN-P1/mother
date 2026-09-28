"""mother — instalador, actualizador y diagnóstico del ecosistema de Programación 1.

_(MU/TH/UR 6000, la computadora de la Nostromo.)_

Solo usa la biblioteca estándar (Python ≥ 3.11) y `uv`: tiene que poder correr
antes de que haya cualquier otra herramienta instalada, y distribuirse como un
único archivo `mother.pyz`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from mother import __version__
from mother.manifiesto import Manifiesto, ManifiestoInvalido, Repo, cargar

SCHEMA_VERSION = "1.0.0"
URL_UV = "https://docs.astral.sh/uv/getting-started/installation/"


@dataclass
class Resultado:
    rc: int
    salida: str
    error: str


def entorno_herramientas() -> dict[str, str]:
    """Entorno para ejecutar las herramientas: salida sin colores y en UTF-8.

    PYTHONIOENCODING: con la salida capturada, en Windows las herramientas escribirían en cp1252 y
    fallarían con UnicodeEncodeError ante un ✓ o un → (p. ej., en su `doctor --json`).
    """
    return dict(os.environ, NO_COLOR="1", TERM="dumb", COLUMNS="200", PYTHONIOENCODING="utf-8")


def correr(args: list[str], timeout: float = 120.0) -> Resultado:
    # Se ejecuta la ruta que encontró shutil.which, el mismo criterio con que se decide si una
    # herramienta está instalada. En Windows, CreateProcess solo prueba la extensión .exe (no ve los
    # lanzadores .cmd/.bat que sí encuentra which) y busca en la carpeta actual antes que en el PATH.
    ejecutable = shutil.which(args[0]) or args[0]
    try:
        proc = subprocess.run([ejecutable, *args[1:]], capture_output=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=entorno_herramientas(), stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return Resultado(127, "", f"no se encontró {args[0]}")
    except subprocess.TimeoutExpired:
        return Resultado(124, "", f"no terminó en {timeout:.0f} s")
    return Resultado(proc.returncode, proc.stdout, proc.stderr)


def _perfiles(args: argparse.Namespace) -> list[str] | None:
    return args.perfil or None


def _instaladas(repos: list[Repo]) -> list[Repo]:
    return [r for r in repos if r.ejecutables and shutil.which(r.ejecutables[0])]


def _tabla(filas: list[list[str]], encabezado: list[str]) -> str:
    anchos = [max(len(str(x)) for x in col) for col in zip(encabezado, *filas, strict=True)]
    lineas = ["  ".join(str(c).ljust(a) for c, a in zip(encabezado, anchos, strict=True)),
              "  ".join("─" * a for a in anchos)]
    lineas += ["  ".join(str(c).ljust(a) for c, a in zip(fila, anchos, strict=True)) for fila in filas]
    return "\n".join(lineas)


# ── comandos ─────────────────────────────────────────────────────────────────────────────

def cmd_listar(args: argparse.Namespace, manifiesto: Manifiesto) -> int:
    repos = manifiesto.seleccionar(_perfiles(args))
    if args.json:
        print(json.dumps([{"nombre": r.nombre, "paquete": r.paquete, "ejecutables": r.ejecutables,
                           "perfiles": r.perfiles, "requisito": r.requisito_git(),
                           "instalada": bool(_instaladas([r]))} for r in repos], ensure_ascii=False, indent=2))
        return 0
    filas = [[r.nombre, ", ".join(r.perfiles), "sí" if _instaladas([r]) else "no"] for r in repos]
    print(_tabla(filas, ["herramienta", "perfiles", "instalada"]))
    print(f"\nManifiesto: {manifiesto.origen}")
    return 0


def cmd_instalar(args: argparse.Namespace, manifiesto: Manifiesto) -> int:
    if not args.perfil and not args.todo:
        print("Indicá qué instalar: --perfil estudiante|analisis|docente|contenido|aula (repetible) o --todo.",
              file=sys.stderr)
        return 2
    if not args.simular and shutil.which("uv") is None:
        print(f"Error: mother instala con uv y no está en el PATH. Instalalo siguiendo {URL_UV}", file=sys.stderr)
        return 1
    fallidas = []
    for repo in manifiesto.seleccionar(None if args.todo else _perfiles(args)):
        comando = ["uv", "tool", "install"]
        if args.forzar:
            comando.append("--force")
        if args.local:
            # --reinstall-package: sin él uv reutiliza una rueda cacheada y se prueba código viejo.
            comando += ["--reinstall-package", repo.paquete, repo.requisito_local(args.local)]
        else:
            comando.append(repo.requisito_git())
        print("$ " + " ".join(f'"{c}"' if " " in c else c for c in comando), flush=True)
        if not args.simular and subprocess.run(comando).returncode != 0:
            fallidas.append(repo.nombre)
    if fallidas:
        print(f"\nNo se pudieron instalar: {', '.join(fallidas)}", file=sys.stderr)
        return 1
    return 0


def cmd_actualizar(args: argparse.Namespace, manifiesto: Manifiesto) -> int:
    repos = _instaladas(manifiesto.seleccionar(_perfiles(args)))
    fallidas = []
    for repo in repos:
        comando = ["uv", "tool", "upgrade", repo.paquete]
        print("$ " + " ".join(comando), flush=True)
        if not args.simular and subprocess.run(comando).returncode != 0:
            fallidas.append(repo.nombre)
    if fallidas:
        print(f"\nNo se pudieron actualizar: {', '.join(fallidas)}", file=sys.stderr)
        return 1
    return 0


def _chequeos_base() -> list[dict]:
    chequeos = [{
        "nombre": "python", "requerido": True, "ok": sys.version_info >= (3, 11),
        "detalle": sys.version.split()[0], "proposito": "Ejecutar mother y las herramientas",
        "sugerencia": "" if sys.version_info >= (3, 11) else "Instalá Python 3.11 o posterior",
    }]
    for nombre, proposito, sugerencia in (
        ("uv", "Instalar y actualizar las herramientas desde git", f"Instalá uv: {URL_UV}"),
        ("git", "Descargar las herramientas de GitHub", "sudo apt install git (o Git for Windows)"),
    ):
        ruta = shutil.which(nombre)
        version = correr([nombre, "--version"], timeout=10).salida.strip().splitlines() if ruta else []
        chequeos.append({"nombre": nombre, "requerido": True, "ok": bool(ruta),
                         "detalle": (version[0] if version else "") if ruta else "No encontrado en el PATH",
                         "proposito": proposito, "sugerencia": "" if ruta else sugerencia})
    return chequeos


def informe_doctor(manifiesto: Manifiesto, perfiles: list[str] | None) -> dict:
    """Doctor agregado: el propio de mother más el `doctor --json` de cada herramienta instalada."""
    chequeos = _chequeos_base()
    herramientas = {}
    requeridas = {r.nombre for r in manifiesto.seleccionar(perfiles)} if perfiles else set()
    for repo in manifiesto.seleccionar(perfiles):
        ejecutable = repo.ejecutables[0]
        if not shutil.which(ejecutable):
            chequeos.append({"nombre": repo.nombre, "requerido": repo.nombre in requeridas, "ok": False,
                             "detalle": "no instalada", "proposito": ", ".join(repo.perfiles),
                             "sugerencia": f"mother instalar --perfil {repo.perfiles[0]}" if repo.perfiles else ""})
            continue
        res = correr([ejecutable, "doctor", "--json"])
        try:
            datos = json.loads(res.salida)
            ok = bool(datos.get("ok", res.rc == 0))
            herramientas[repo.nombre] = datos
            fallas = [c.get("nombre", "?") for c in datos.get("chequeos", []) if c.get("requerido") and not c.get("ok")]
            detalle = "doctor ok" if ok else f"faltan: {', '.join(fallas) or 'ver su doctor'}"
        except (json.JSONDecodeError, AttributeError):
            ok, detalle = False, f"doctor --json no devolvió JSON (código {res.rc})"
        chequeos.append({"nombre": repo.nombre, "requerido": repo.nombre in requeridas, "ok": ok, "detalle": detalle,
                         "proposito": ", ".join(repo.perfiles),
                         "sugerencia": "" if ok else f"{ejecutable} doctor"})
    return {
        "schema_version": SCHEMA_VERSION,
        "herramienta": "mother",
        "version": __version__,
        "ok": all(c["ok"] for c in chequeos if c["requerido"]),
        "chequeos": chequeos,
        "herramientas": herramientas,
        "manifiesto": manifiesto.origen,
    }


def cmd_doctor(args: argparse.Namespace, manifiesto: Manifiesto) -> int:
    datos = informe_doctor(manifiesto, _perfiles(args))
    if args.json:
        print(json.dumps(datos, ensure_ascii=False, indent=2))
    else:
        filas = [[c["nombre"], "✓" if c["ok"] else ("✗" if c["requerido"] else "–"), c["detalle"],
                  c["sugerencia"]] for c in datos["chequeos"]]
        print(_tabla(filas, ["componente", "estado", "detalle", "cómo resolverlo"]))
        print("\n✓ Está todo lo requerido." if datos["ok"] else "\n✗ Falta al menos un componente requerido.")
    return 0 if datos["ok"] else 1


def cmd_versiones(args: argparse.Namespace, manifiesto: Manifiesto) -> int:
    filas = []
    for repo in manifiesto.seleccionar(_perfiles(args)):
        ejecutable = repo.ejecutables[0]
        if shutil.which(ejecutable):
            lineas = correr([ejecutable, "--version"], timeout=30).salida.strip().splitlines()
            instalada = lineas[0] if lineas else "?"
        else:
            instalada = "no instalada"
        filas.append({"herramienta": repo.nombre, "instalada": instalada, "esperada": repo.ref or "rama principal"})
    if args.json:
        print(json.dumps(filas, ensure_ascii=False, indent=2))
    else:
        print(_tabla([list(f.values()) for f in filas], ["herramienta", "instalada", "esperada (manifiesto)"]))
    return 0


def contrato(ejecutable: str) -> dict:
    """-h/--help, --version/-v y doctor --json (LINEAMIENTOS §3.2)."""
    resultado: dict = {"ejecutable": ejecutable}
    for opcion in ("--help", "-h", "--version", "-v"):
        res = correr([ejecutable, opcion])
        resultado[opcion] = res.rc == 0 and "Traceback" not in res.salida + res.error
    res = correr([ejecutable, "doctor", "--json"])
    try:
        resultado["doctor --json"] = "schema_version" in json.loads(res.salida)
    except (json.JSONDecodeError, TypeError):
        resultado["doctor --json"] = False
    resultado["cumple"] = all(v for k, v in resultado.items() if k != "ejecutable")
    return resultado


def cmd_autoprueba(args: argparse.Namespace, manifiesto: Manifiesto) -> int:
    repos = manifiesto.seleccionar(_perfiles(args))
    instaladas = _instaladas(repos)
    faltan = [r.nombre for r in repos if r not in instaladas]
    resultados = [contrato(r.ejecutables[0]) for r in instaladas]
    if args.json:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "resultados": resultados, "no_instaladas": faltan},
                         ensure_ascii=False, indent=2))
    else:
        columnas = ["--help", "-h", "--version", "-v", "doctor --json"]
        print(_tabla([[r["ejecutable"], *("✓" if r[c] else "✗" for c in columnas)] for r in resultados],
                     ["ejecutable", *columnas]))
        cumplen = sum(r["cumple"] for r in resultados)
        print(f"\nCumplen el contrato: {cumplen}/{len(resultados)}")
        if faltan:
            print(f"No instaladas: {', '.join(faltan)}")
    return 0 if all(r["cumple"] for r in resultados) and not (faltan and args.perfil) else 1


def cmd_sistema(args: argparse.Namespace, manifiesto: Manifiesto) -> int:
    requeridos = sorted({s for r in manifiesto.seleccionar(_perfiles(args)) for s in r.sistema})
    faltan = [s for s in requeridos if shutil.which(s) is None]
    for programa in requeridos:
        print(f"{'✓' if programa not in faltan else '✗'} {programa}")
    return 1 if faltan else 0


# ── entrada ──────────────────────────────────────────────────────────────────────────────

def _salida_en_utf8() -> None:
    """Escribe en UTF-8 aunque la salida esté redirigida.

    En Windows, con la salida redirigida (a un archivo, a otro programa o en un runner de CI),
    Python escribe con la página de códigos (cp1252) y los ✓, ✗ y ─ de las tablas hacían fallar a
    mother con UnicodeEncodeError. La consola de Windows ya escribe en UTF-8 (PEP 528).
    """
    for flujo in (sys.stdout, sys.stderr):
        codificacion = (getattr(flujo, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if codificacion != "utf8" and hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mother",
        description="Instala, actualiza y diagnostica las herramientas del ecosistema de Programación 1 "
                    "(siempre desde git, nunca por nombre en PyPI).",
    )
    parser.add_argument("-v", "--version", action="version", version=f"mother {__version__}")
    parser.add_argument("--manifiesto", help="ruta o URL de ecosistema.toml (por defecto, el publicado en p1-tools)")
    parser.add_argument("--sin-red", action="store_true", help="no descargar el manifiesto: usar la caché o la copia incluida")
    sub = parser.add_subparsers(dest="comando", metavar="COMANDO")

    def perfil(p: argparse.ArgumentParser) -> None:
        p.add_argument("--perfil", action="append", metavar="PERFIL",
                       help="estudiante, analisis, docente, contenido o aula (repetible)")

    p = sub.add_parser("listar", help="herramientas del manifiesto y si están instaladas")
    perfil(p)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("instalar", help="instala las herramientas de un perfil desde git")
    perfil(p)
    p.add_argument("--todo", action="store_true", help="todas las herramientas activas")
    p.add_argument("--local", type=lambda s: __import__("pathlib").Path(s), metavar="RAIZ",
                   help="instalar desde clones locales en RAIZ/<carpeta> (prueba sin el monorepo)")
    p.add_argument("--forzar", action="store_true", help="reinstalar aunque ya esté instalada (uv --force)")
    p.add_argument("--simular", action="store_true", help="mostrar los comandos sin ejecutarlos")

    p = sub.add_parser("actualizar", help="actualiza las herramientas instaladas")
    perfil(p)
    p.add_argument("--simular", action="store_true")

    p = sub.add_parser("doctor", help="diagnóstico agregado: mother más el doctor de cada herramienta")
    perfil(p)
    p.add_argument("--json", action="store_true", help="informe JSON con schema_version")

    p = sub.add_parser("versiones", help="versión instalada de cada herramienta")
    perfil(p)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("autoprueba", help="verifica el contrato de línea de comandos de lo instalado")
    perfil(p)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("sistema", help="programas del sistema que necesita un perfil (gcc, gdb…)")
    perfil(p)
    return parser


COMANDOS = {"listar": cmd_listar, "instalar": cmd_instalar, "actualizar": cmd_actualizar, "doctor": cmd_doctor,
            "versiones": cmd_versiones, "autoprueba": cmd_autoprueba, "sistema": cmd_sistema}


def main(argv: list[str] | None = None) -> int:
    _salida_en_utf8()
    parser = construir_parser()
    args = parser.parse_args(argv)
    if args.comando is None:
        parser.print_help()
        return 0
    try:
        manifiesto = cargar(args.manifiesto, usar_red=not args.sin_red)
        return COMANDOS[args.comando](args, manifiesto)
    except ManifiestoInvalido as error:
        if os.environ.get("P1_DEPURAR"):
            raise
        print(f"Error: {error}", file=sys.stderr)
        return 1


def _principal() -> None:
    """Punto de entrada del zipapp (zipapp no usa el código de salida de main)."""
    sys.exit(main())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
