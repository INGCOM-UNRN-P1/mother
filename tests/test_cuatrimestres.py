"""Matriz de versiones por cuatrimestre (revisión 07, mother)."""

import pytest

from mother import cli
from mother.manifiesto import ManifiestoInvalido, interpretar

BASE = """
schema_version = 1
cuatrimestre_vigente = "2026-2"

[perfiles]
estudiante = "x"

[[repo]]
nombre = "gaff"
tipo = "cli"
estado = "activo"
url = "https://github.com/INGCOM-UNRN-P1/gaff"
paquete = "gaff"
ejecutables = ["gaff"]
perfiles = ["estudiante"]

[[repo]]
nombre = "hal"
tipo = "cli"
estado = "activo"
url = "https://github.com/INGCOM-UNRN-P1/hal"
paquete = "hal"
ejecutables = ["hal"]
perfiles = ["estudiante"]

[cuatrimestres."2026-1"]
gaff = "v0.1.0"

[cuatrimestres."2026-2"]
gaff = "v0.3.0"
hal = "abc123"
"""


def test_aplica_el_vigente_y_uno_elegido():
    m = interpretar(BASE, "prueba")
    assert m.aplicar_cuatrimestre(None) == "2026-2"
    assert {r.nombre: r.ref for r in m.repos} == {"gaff": "v0.3.0", "hal": "abc123"}
    assert m.repos[0].requisito_git().endswith("@v0.3.0")
    m = interpretar(BASE, "prueba")
    m.aplicar_cuatrimestre("2026-1")
    assert {r.nombre: r.ref for r in m.repos} == {"gaff": "v0.1.0", "hal": ""}


def test_errores():
    with pytest.raises(ManifiestoInvalido, match="cuatrimestre desconocido"):
        interpretar(BASE, "prueba").aplicar_cuatrimestre("2030-1")
    with pytest.raises(ManifiestoInvalido, match="no es un repo"):
        interpretar(BASE + '\n[cuatrimestres."2027-1"]\nnada = "v1"\n', "prueba")
    with pytest.raises(ManifiestoInvalido, match="cuatrimestre_vigente"):
        interpretar(BASE.replace('"2026-2"\n\n[perfiles]', '"2029-9"\n\n[perfiles]'), "prueba")


def test_fijar(monkeypatch, capsys, tmp_path):
    archivo = tmp_path / "eco.toml"
    archivo.write_text(BASE, encoding="utf-8")
    monkeypatch.setattr(cli, "correr", lambda args, timeout=120.0: cli.Resultado(0, "deadbeef\tHEAD\n", ""))
    assert cli.main(["--manifiesto", str(archivo), "fijar", "2027-1"]) == 0
    salida = capsys.readouterr().out
    assert '[cuatrimestres."2027-1"]' in salida and 'gaff = "deadbeef' in salida
