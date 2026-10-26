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


# ── auditar (Ola 11): nada fijado a una rama ni a un commit abreviado ───────────────────────────

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def test_auditar_marca_lo_mutable_y_lo_sin_fijar():
    m = interpretar(BASE, "prueba")
    datos = cli.auditar_matriz(m, None, None)
    assert datos["cuatrimestre"] == "2026-2" and datos["fijadas"] == {"gaff": "v0.3.0", "hal": "abc123"}
    assert len(datos["problemas"]) == 1 and "«abc123» no es un tag" in datos["problemas"][0]
    viejo = cli.auditar_matriz(m, "2026-1", None)
    assert viejo["problemas"] == ["hal: sin fijar en 2026-1: se instalaría la rama principal (mutable)"]
    rama = interpretar(BASE.replace('hal = "abc123"', 'hal = "main"'), "prueba")
    assert "«main» no es un tag" in cli.auditar_matriz(rama, None, None)["problemas"][0]


def test_auditar_acepta_tags_y_commits_completos_y_solo_tags():
    m = interpretar(BASE.replace('hal = "abc123"', f'hal = "{COMMIT}"'), "prueba")
    assert cli.auditar_matriz(m, None, None)["problemas"] == []
    (problema,) = cli.auditar_matriz(m, None, None, solo_tags=True)["problemas"]
    assert problema.startswith("hal: fijada a un commit")


def test_auditar_remoto(monkeypatch):
    m = interpretar(BASE.replace('hal = "abc123"', 'hal = "v1.0.0"'), "prueba")
    salidas = {"gaff": "x\trefs/tags/v0.3.0\n", "hal": "y\trefs/heads/v1.0.0\n"}

    def correr(args, timeout=0):
        return cli.Resultado(0, salidas[args[2].rsplit("/", 1)[1]], "")

    monkeypatch.setattr(cli, "correr", correr)
    assert cli.auditar_matriz(m, None, None, remoto=True)["problemas"] == [
        "hal: «v1.0.0» también es una rama de https://github.com/INGCOM-UNRN-P1/hal"]
    salidas["hal"] = ""
    assert "no está publicado" in cli.auditar_matriz(m, None, None, remoto=True)["problemas"][0]


def test_cli_auditar(tmp_path, capsys):
    ruta = tmp_path / "ecosistema.toml"
    ruta.write_text(BASE, encoding="utf-8")
    assert cli.main(["--manifiesto", str(ruta), "auditar"]) == 1
    assert "✗ hal" in capsys.readouterr().out
    sin_vigente = BASE.replace('cuatrimestre_vigente = "2026-2"\n', "")
    ruta.write_text(sin_vigente, encoding="utf-8")
    assert cli.main(["--manifiesto", str(ruta), "auditar"]) == 0
    assert "rama principal" in capsys.readouterr().out
    assert cli.main(["--manifiesto", str(ruta), "auditar", "--exigir-vigente", "--json"]) == 1
    assert '"ok": false' in capsys.readouterr().out
