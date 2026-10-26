"""`mother doctor --fix`: shims huérfanos, permisos y enlaces faltantes (Ola 11, QoL #182)."""

from __future__ import annotations

import json
import os
import stat
import textwrap
from pathlib import Path

import pytest

from mother import cli
from mother.manifiesto import interpretar
from mother.reparar import aplicar, diagnosticar

pytestmark = pytest.mark.skipif(os.name == "nt", reason="los enlaces simbólicos de uv son de Linux y macOS")

MANIFIESTO = """
[perfiles]
estudiante = "Estudiantes"

[[repo]]
nombre = "hal"
url = "https://github.com/INGCOM-UNRN-P1/hal"
tipo = "cli"
paquete = "hal"
ejecutables = ["hal"]
perfiles = ["estudiante"]
estado = "activo"

[[repo]]
nombre = "gaff"
url = "https://github.com/INGCOM-UNRN-P1/gaff"
tipo = "cli"
paquete = "gaff"
ejecutables = ["gaff"]
perfiles = ["estudiante"]
estado = "activo"

[[repo]]
nombre = "ripley"
url = "https://github.com/INGCOM-UNRN-P1/ripley"
tipo = "cli"
paquete = "ripley"
ejecutables = ["ripley", "ripley-check"]
perfiles = ["estudiante"]
estado = "activo"
"""


def _entorno(entornos: Path, paquete: str, *ejecutables: str, ejecutable: bool = True) -> None:
    for nombre in ejecutables:
        ruta = entornos / paquete / "bin" / nombre
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        ruta.chmod(0o755 if ejecutable else 0o644)


@pytest.fixture
def uv_falso(tmp_path: Path, monkeypatch):
    """hal sano; gaff sin entorno (shim huérfano); ripley sin enlace a ripley-check y sin permiso;
    un enlace roto de una herramienta retirada y un archivo ajeno en bin."""
    entornos, binarios = tmp_path / "tools", tmp_path / "bin"
    binarios.mkdir()
    _entorno(entornos, "hal", "hal")
    (binarios / "hal").symlink_to(entornos / "hal" / "bin" / "hal")
    (binarios / "gaff").symlink_to(entornos / "gaff" / "bin" / "gaff")
    _entorno(entornos, "ripley", "ripley", "ripley-check", ejecutable=False)
    (binarios / "ripley").symlink_to(entornos / "ripley" / "bin" / "ripley")
    (binarios / "keymaker").symlink_to(entornos / "keymaker" / "bin" / "keymaker")
    (binarios / "ajeno").symlink_to(tmp_path / "otro-lado" / "ajeno")  # roto, pero no es de uv
    monkeypatch.setattr("mother.reparar.directorios_uv", lambda: (entornos, binarios))
    return entornos, binarios


def _repos():
    return interpretar(textwrap.dedent(MANIFIESTO), "prueba").seleccionar()


def test_diagnostica_sin_tocar(uv_falso):
    entornos, binarios = uv_falso
    pendientes = {(r.accion, Path(r.objetivo).name) for r in diagnosticar(_repos(), entornos, binarios)}
    assert pendientes == {
        ("quitar-shim-huerfano", "gaff"), ("quitar-shim-huerfano", "keymaker"),
        ("rehacer-enlace", "ripley-check"),
        ("permiso-de-ejecucion", "ripley"), ("permiso-de-ejecucion", "ripley-check"),
    }
    assert (binarios / "gaff").is_symlink() and not (binarios / "ripley-check").exists()


def test_aplica_las_reparaciones(uv_falso):
    entornos, binarios = uv_falso
    reparaciones = diagnosticar(_repos(), entornos, binarios)
    aplicar(reparaciones)
    assert all(r.hecha for r in reparaciones)
    assert not (binarios / "gaff").is_symlink() and not (binarios / "keymaker").is_symlink()
    assert os.readlink(binarios / "ripley-check") == str(entornos / "ripley" / "bin" / "ripley-check")
    assert os.access(entornos / "ripley" / "bin" / "ripley", os.X_OK)
    assert (entornos / "ripley" / "bin" / "ripley").stat().st_mode & stat.S_IXOTH
    assert (binarios / "ajeno").is_symlink()  # lo que no es de uv no se toca
    assert diagnosticar(_repos(), entornos, binarios) == []


def test_cli_doctor_fix(uv_falso, tmp_path, capsys):
    manifiesto = tmp_path / "ecosistema.toml"
    manifiesto.write_text(textwrap.dedent(MANIFIESTO), encoding="utf-8")
    _, binarios = uv_falso
    cli.main(["--manifiesto", str(manifiesto), "doctor", "--fix", "--simular"])
    salida = capsys.readouterr().out
    assert "· quitar-shim-huerfano" in salida and "simulación" in salida and (binarios / "gaff").is_symlink()
    cli.main(["--manifiesto", str(manifiesto), "doctor", "--fix", "--json"])
    datos = json.loads(capsys.readouterr().out)
    assert len(datos["reparaciones"]) == 5 and all(r["hecha"] for r in datos["reparaciones"])
    comandos = next(c for c in datos["chequeos"] if c["nombre"] == "comandos")
    assert comandos["ok"] and not comandos["requerido"]


def test_doctor_sin_fix_sugiere_repararlo(uv_falso, tmp_path, capsys):
    manifiesto = tmp_path / "ecosistema.toml"
    manifiesto.write_text(textwrap.dedent(MANIFIESTO), encoding="utf-8")
    cli.main(["--manifiesto", str(manifiesto), "doctor", "--json"])
    comandos = next(c for c in json.loads(capsys.readouterr().out)["chequeos"] if c["nombre"] == "comandos")
    assert not comandos["ok"] and comandos["sugerencia"] == "mother doctor --fix" and "gaff" in comandos["detalle"]


def test_fix_sin_uv(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("mother.reparar.directorios_uv", lambda: (None, None))
    manifiesto = tmp_path / "ecosistema.toml"
    manifiesto.write_text(textwrap.dedent(MANIFIESTO), encoding="utf-8")
    assert cli.main(["--manifiesto", str(manifiesto), "doctor", "--fix"]) == 1
    assert "uv no está en el PATH" in capsys.readouterr().err
