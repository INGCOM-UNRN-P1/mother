"""Tests de mother con manifiestos y herramientas falsas (sin red ni instalaciones reales)."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import textwrap
import urllib.error
from importlib import resources
from pathlib import Path

import pytest

from mother import cli, manifiesto
from mother.manifiesto import ManifiestoInvalido, cargar, interpretar

MANIFIESTO = """
[perfiles]
estudiante = "Estudiantes"
docente = "Docentes"

[[repo]]
nombre = "falsa"
url = "https://github.com/INGCOM-UNRN-P1/falsa"
tipo = "cli"
paquete = "falsa"
ejecutables = ["falsa"]
perfiles = ["estudiante"]
sistema = ["sh"]
estado = "activo"

[[repo]]
nombre = "rota"
url = "https://github.com/INGCOM-UNRN-P1/rota"
tipo = "cli"
paquete = "rota"
ejecutables = ["rota"]
perfiles = ["docente"]
estado = "activo"

[[repo]]
nombre = "questions"
url = "https://github.com/INGCOM-UNRN/moodle-toolbox"
tipo = "cli"
paquete = "questions"
ejecutables = ["no-instalada-nunca"]
extras = ["ai"]
perfiles = ["docente"]
ref = "v1.2.0"
estado = "activo"

[[repo]]
nombre = "nueva"
url = "https://github.com/INGCOM-UNRN-P1/nueva"
tipo = "biblioteca"
paquete = "nueva"
estado = "sin-publicar"
"""

HERRAMIENTA = """
if args in (["-h"], ["--help"]):
    print("uso: falsa")
elif args in (["--version"], ["-v"]):
    print("falsa 2.0.0")
elif args == ["doctor", "--json"]:
    print(json.dumps({"schema_version": "1.0.0", "herramienta": "falsa", "ok": OK,
                      "chequeos": [{"nombre": "gcc", "requerido": True, "ok": OK, "detalle": "✓ → compilación"}]},
                     ensure_ascii=False))
    sys.exit(0 if OK else 1)
else:
    sys.exit(2)
"""


@pytest.fixture
def ruta_manifiesto(tmp_path: Path) -> Path:
    ruta = tmp_path / "ecosistema.toml"
    ruta.write_text(textwrap.dedent(MANIFIESTO), encoding="utf-8")
    return ruta


@pytest.fixture
def herramientas(tmp_path: Path, monkeypatch) -> Path:
    """`falsa` cumple y su doctor da ok; `rota` no tiene contrato y su doctor falla."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for nombre, cuerpo in (("falsa", HERRAMIENTA.replace("OK", "True")),
                           ("rota", HERRAMIENTA.replace("OK", "False").replace('(["-h"], ["--help"])', '(["--help"],)'))):
        codigo = f"import sys, json\nargs = sys.argv[1:]\n{cuerpo}\n"
        if os.name == "nt":
            # Windows no ejecuta scripts con shebang ni los encuentra sin extensión: un lanzador .cmd
            # (que shutil.which encuentra por PATHEXT) llama al intérprete con el script.
            (bin_dir / f"{nombre}-herramienta.py").write_text(codigo, encoding="utf-8")
            (bin_dir / f"{nombre}.cmd").write_text(
                f'@"{sys.executable}" "%~dp0{nombre}-herramienta.py" %*\n@exit /b %ERRORLEVEL%\n', encoding="utf-8")
        else:
            ruta = bin_dir / nombre
            ruta.write_text(f"#!{sys.executable}\n{codigo}", encoding="utf-8")
            ruta.chmod(ruta.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


def _mother(ruta_manifiesto: Path, *args: str) -> int:
    return cli.main(["--manifiesto", str(ruta_manifiesto), *args])


# ── manifiesto ───────────────────────────────────────────────────────────────────────────

def test_requisitos_siempre_desde_git(ruta_manifiesto):
    repos = {r.nombre: r for r in cargar(str(ruta_manifiesto)).repos}
    assert repos["falsa"].requisito_git() == "git+https://github.com/INGCOM-UNRN-P1/falsa"
    assert repos["questions"].requisito_git() == "questions[ai] @ git+https://github.com/INGCOM-UNRN/moodle-toolbox@v1.2.0"


def test_sin_publicar_no_es_instalable(ruta_manifiesto):
    nombres = [r.nombre for r in cargar(str(ruta_manifiesto)).seleccionar()]
    assert "nueva" not in nombres and "falsa" in nombres


@pytest.mark.parametrize("texto, mensaje", [
    ('[perfiles]\n[[repo]]\nnombre = "x"\ntipo = "cli"\nestado = "activo"\nurl = "u"', "necesita `paquete`"),
    ('[perfiles]\n[[repo]]\nnombre = "x"\ntipo = "contenido"\nestado = "activo"\nperfiles = ["p"]', "perfil desconocido"),
    ('[perfiles]\n[[repo]]\nnombre = "x"\ntipo = "contenido"\nestado = "activo"\ncampo_raro = 1', "campo_raro"),
    ("esto no es toml = = =", "no es un TOML válido"),
])
def test_manifiesto_invalido(texto, mensaje):
    with pytest.raises(ManifiestoInvalido, match=mensaje):
        interpretar(texto, "prueba")


def test_tipos_y_estados_nuevos_no_rompen():
    """Un manifiesto más nuevo que mother (tipos o estados que no conoce) se sigue leyendo."""
    manifiesto = interpretar(
        '[perfiles]\ndocente = "d"\n\n[[repo]]\nnombre = "sulaco"\ntipo = "workflows"\n'
        'estado = "futuro"\nperfiles = ["docente"]\n', "prueba")
    assert [r.nombre for r in manifiesto.repos] == ["sulaco"]
    assert manifiesto.seleccionar(["docente"]) == []


def test_perfil_desconocido(ruta_manifiesto, capsys):
    assert _mother(ruta_manifiesto, "listar", "--perfil", "inexistente") == 1
    assert "perfil desconocido" in capsys.readouterr().err


def test_sin_red_usa_la_cache_y_luego_la_copia_incluida(tmp_path, monkeypatch):
    monkeypatch.delenv(manifiesto.VARIABLE_MANIFIESTO, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    def sin_red(url, timeout=10.0):
        raise urllib.error.URLError("sin red")

    monkeypatch.setattr(manifiesto, "_descargar", sin_red)
    incluida = cargar()
    assert incluida.origen == "copia incluida en mother"
    assert any(r.nombre == "ripley" for r in incluida.repos)

    cache = tmp_path / "cache" / "mother" / "ecosistema.toml"
    cache.parent.mkdir(parents=True)
    cache.write_text(textwrap.dedent(MANIFIESTO), encoding="utf-8")
    assert "caché" in cargar().origen


def test_descarga_y_guarda_en_cache(tmp_path, monkeypatch):
    monkeypatch.delenv(manifiesto.VARIABLE_MANIFIESTO, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(manifiesto, "_descargar", lambda url, timeout=10.0: textwrap.dedent(MANIFIESTO))
    assert cargar().origen == manifiesto.URL_MANIFIESTO
    assert (tmp_path / "cache" / "mother" / "ecosistema.toml").is_file()


def test_la_url_del_manifiesto_es_la_del_repo_de_p1_tools():
    """El manifiesto se descarga del repo en que se publica p1-tools (su `url` en el propio manifiesto)."""
    incluida = (resources.files("mother") / "ecosistema.toml").read_text(encoding="utf-8")
    p1_tools = next(r for r in interpretar(incluida, "copia incluida").repos if r.nombre == "p1-tools")
    repo = p1_tools.url.removeprefix("https://github.com/")
    assert manifiesto.URL_MANIFIESTO == f"https://raw.githubusercontent.com/{repo}/main/ecosistema.toml"


def test_variable_de_entorno(ruta_manifiesto, monkeypatch):
    monkeypatch.setenv(manifiesto.VARIABLE_MANIFIESTO, str(ruta_manifiesto))
    assert cargar().origen == str(ruta_manifiesto)


# ── instalar ─────────────────────────────────────────────────────────────────────────────

def test_instalar_exige_perfil(ruta_manifiesto, capsys):
    assert _mother(ruta_manifiesto, "instalar", "--simular") == 2
    assert "--perfil" in capsys.readouterr().err


def test_instalar_simulado(ruta_manifiesto, capsys):
    assert _mother(ruta_manifiesto, "instalar", "--perfil", "docente", "--simular") == 0
    salida = capsys.readouterr().out.splitlines()
    assert salida == ["$ uv tool install git+https://github.com/INGCOM-UNRN-P1/rota",
                      '$ uv tool install "questions[ai] @ git+https://github.com/INGCOM-UNRN/moodle-toolbox@v1.2.0"']


def test_instalar_local_y_forzado(ruta_manifiesto, capsys):
    _mother(ruta_manifiesto, "instalar", "--perfil", "estudiante", "--local", "/raiz", "--forzar", "--simular")
    ruta = Path("/raiz") / "falsa"  # con el separador del sistema: \raiz\falsa en Windows
    assert capsys.readouterr().out.strip() == f"$ uv tool install --force --reinstall-package falsa {ruta}"


# ── doctor, versiones, autoprueba, sistema ───────────────────────────────────────────────

def test_doctor_agregado(ruta_manifiesto, herramientas, capsys):
    codigo = _mother(ruta_manifiesto, "doctor", "--perfil", "estudiante", "--json")
    datos = json.loads(capsys.readouterr().out)
    assert datos["schema_version"] == "1.0.0" and datos["herramienta"] == "mother"
    por_nombre = {c["nombre"]: c for c in datos["chequeos"]}
    assert por_nombre["falsa"]["ok"] and por_nombre["falsa"]["requerido"]
    assert datos["herramientas"]["falsa"]["herramienta"] == "falsa"
    assert codigo == (0 if datos["ok"] else 1)


def test_doctor_lee_en_utf8_la_salida_de_las_herramientas(ruta_manifiesto, herramientas, capsys, monkeypatch):
    """Con la salida capturada, en Windows las herramientas escribirían en cp1252 y el ✓ de su
    `doctor --json` las haría fallar; mother les pide UTF-8 y lo lee así."""
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")  # lo que heredan en Windows
    _mother(ruta_manifiesto, "doctor", "--perfil", "estudiante", "--json")
    datos = json.loads(capsys.readouterr().out)
    assert datos["herramientas"]["falsa"]["chequeos"][0]["detalle"] == "✓ → compilación"


def test_doctor_falla_si_una_herramienta_requerida_falla(ruta_manifiesto, herramientas, capsys):
    codigo = _mother(ruta_manifiesto, "doctor", "--perfil", "docente", "--json")
    datos = json.loads(capsys.readouterr().out)
    por_nombre = {c["nombre"]: c for c in datos["chequeos"]}
    assert por_nombre["rota"]["ok"] is False and "gcc" in por_nombre["rota"]["detalle"]
    assert por_nombre["questions"]["detalle"] == "no instalada"
    assert codigo == 1 and datos["ok"] is False


def test_versiones(ruta_manifiesto, herramientas, capsys):
    _mother(ruta_manifiesto, "versiones", "--json")
    filas = {f["herramienta"]: f for f in json.loads(capsys.readouterr().out)}
    assert filas["falsa"]["instalada"] == "falsa 2.0.0"
    assert filas["questions"] == {"herramienta": "questions", "instalada": "no instalada", "esperada": "v1.2.0"}


def test_autoprueba(ruta_manifiesto, herramientas, capsys):
    assert _mother(ruta_manifiesto, "autoprueba", "--perfil", "estudiante") == 0
    assert _mother(ruta_manifiesto, "autoprueba", "--perfil", "docente", "--json") == 1
    datos = json.loads(capsys.readouterr().out.split("Cumplen el contrato")[-1].split("\n", 1)[-1])
    rota = next(r for r in datos["resultados"] if r["ejecutable"] == "rota")
    assert rota["-h"] is False and rota["--help"] is True
    assert datos["no_instaladas"] == ["questions"]


def test_sistema(ruta_manifiesto, capsys):
    assert _mother(ruta_manifiesto, "sistema", "--perfil", "estudiante") == 0
    assert "✓ sh" in capsys.readouterr().out


# ── salida redirigida en Windows ─────────────────────────────────────────────────────────

# Con la salida redirigida (archivo, otro programa, runner de CI), Python en Windows escribe
# con la página de códigos; PYTHONIOENCODING=cp1252 reproduce ese caso en cualquier sistema.
SALIDA_WINDOWS = dict(os.environ, PYTHONIOENCODING="cp1252")


@pytest.mark.parametrize("args, simbolo", [
    (["listar"], "─"),
    (["sistema", "--perfil", "estudiante"], " sh"),
    (["doctor", "--perfil", "estudiante"], "─"),
])
def test_salida_redirigida_en_windows(ruta_manifiesto, args, simbolo):
    proc = subprocess.run([sys.executable, "-m", "mother", "--manifiesto", str(ruta_manifiesto), *args],
                          capture_output=True, env=SALIDA_WINDOWS, timeout=120)
    error = proc.stderr.decode("utf-8", "replace")
    assert "Traceback" not in error and proc.returncode in (0, 1), error
    assert simbolo in proc.stdout.decode("utf-8")


# ── contrato de mother ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("opcion", ["-h", "--help", "-v", "--version"])
def test_contrato_propio(opcion, capsys):
    with pytest.raises(SystemExit) as salida:
        cli.main([opcion])
    assert salida.value.code == 0
    assert capsys.readouterr().out.strip()


def test_sin_comando_muestra_la_ayuda(capsys):
    assert cli.main([]) == 0
    assert "instalar" in capsys.readouterr().out


def test_la_ayuda_y_los_errores_de_uso_estan_en_espanol(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    ayuda = capsys.readouterr().out
    assert ayuda.startswith("uso: mother") and "muestra esta ayuda y sale" in ayuda

    with pytest.raises(SystemExit) as salida:
        cli.main(["nada"])
    assert salida.value.code == 2
    # Según la versión de Python, argparse cita las opciones ('listar') o no (listar).
    assert re.search(r"'nada' no es ninguna de estas opciones: '?listar'?, ", capsys.readouterr().err)

    with pytest.raises(SystemExit) as salida:
        cli.main(["instalar", "--perfil"])
    assert salida.value.code == 2
    assert "argumento --perfil: necesita un valor" in capsys.readouterr().err


def test_zipapp(tmp_path):
    raiz = Path(__file__).resolve().parents[1]
    destino = tmp_path / "mother.pyz"
    construccion = subprocess.run([sys.executable, str(raiz / "scripts" / "construir_zipapp.py"), "--salida",
                                   str(destino)], capture_output=True, env=SALIDA_WINDOWS)
    assert construccion.returncode == 0, construccion.stderr.decode("utf-8", "replace")
    salida = subprocess.run([sys.executable, str(destino), "--version"], capture_output=True, text=True)
    assert salida.returncode == 0 and salida.stdout.startswith("mother ")
    listado = subprocess.run([sys.executable, str(destino), "--sin-red", "listar", "--json"],
                             capture_output=True, text=True, env=dict(os.environ, XDG_CACHE_HOME=str(tmp_path)))
    assert listado.returncode == 0, listado.stderr
    assert any(r["nombre"] == "ripley" for r in json.loads(listado.stdout))
    tabla = subprocess.run([sys.executable, str(destino), "--sin-red", "listar"], capture_output=True,
                           env=dict(SALIDA_WINDOWS, XDG_CACHE_HOME=str(tmp_path)))
    assert tabla.returncode == 0, tabla.stderr.decode("utf-8", "replace")
    assert "ripley" in tabla.stdout.decode("utf-8")
