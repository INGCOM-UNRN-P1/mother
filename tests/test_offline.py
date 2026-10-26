"""Paquete offline: `empaquetar-offline` e `instalar --desde-archivo` (Ola 11)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import sysconfig
import tarfile
import textwrap
from pathlib import Path

import pytest

from mother import cli, offline
from mother.manifiesto import interpretar

MANIFIESTO = """
[perfiles]
estudiante = "e"

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
extras = ["ecosistema"]
perfiles = ["estudiante"]
estado = "activo"
"""

# Las ruedas que «arma» pip para cada herramienta: typer igual en las dos; yutani con el mismo nombre
# y distinto contenido (cada una lo fija a otro commit).
RUEDAS = {
    "hal": {"hal-0.2.0-py3-none-any.whl": b"hal", "typer-0.27.3-py3-none-any.whl": b"typer",
            "yutani-0.1.0-py3-none-any.whl": b"yutani A"},
    "gaff": {"gaff-1.0.0-py3-none-any.whl": b"gaff", "typer-0.27.3-py3-none-any.whl": b"typer",
             "yutani-0.1.0-py3-none-any.whl": b"yutani B"},
}


@pytest.fixture
def paquete(tmp_path, monkeypatch) -> Path:
    def ruedas(repo, python, destino):
        destino.mkdir(parents=True, exist_ok=True)
        for nombre, contenido in RUEDAS[repo.nombre].items():
            (destino / nombre).write_bytes(contenido)
        return sorted(destino.glob("*.whl"))

    monkeypatch.setattr(offline, "_ruedas", ruedas)
    monkeypatch.setattr(offline.shutil, "which", lambda nombre: "/usr/bin/" + nombre)
    salida = tmp_path / "paquete.tar.gz"
    repos = interpretar(textwrap.dedent(MANIFIESTO), "prueba").seleccionar(["estudiante"])
    offline.empaquetar(repos, salida, perfiles=["estudiante"], cuatrimestre=None, python="3.12", zipapps=False)
    return salida


def _leer(salida: Path) -> dict:
    with tarfile.open(salida) as tar:
        return json.load(tar.extractfile("paquete/paquete.json"))


def test_empaquetar_deduplica_y_separa_las_ruedas_distintas(paquete):
    datos = _leer(paquete)
    assert datos["python"] == "3.12" and datos["plataforma"] == sysconfig.get_platform()
    hal, gaff = datos["herramientas"]
    assert hal["rueda"] == "ruedas/hal-0.2.0-py3-none-any.whl" and gaff["extras"] == ["ecosistema"]
    assert "ruedas/typer-0.27.3-py3-none-any.whl" in hal["ruedas"] and "ruedas/typer-0.27.3-py3-none-any.whl" in gaff["ruedas"]
    assert "ruedas/yutani-0.1.0-py3-none-any.whl" in hal["ruedas"]
    assert "ruedas/gaff/yutani-0.1.0-py3-none-any.whl" in gaff["ruedas"]
    assert len(datos["archivos"]) == 5 and all(len(s) == 64 for s in datos["archivos"].values())


def test_instalar_simulado_usa_las_ruedas_locales(paquete, capsys):
    assert offline.instalar_desde_archivo(paquete, simular=True) == 0
    salida = capsys.readouterr().out
    assert "Paquete íntegro: 5 archivos" in salida
    lineas = [l for l in salida.splitlines() if l.startswith("$ uv tool install")]
    assert len(lineas) == 2 and all("--offline --no-index --find-links" in l and "--python 3.12" in l for l in lineas)
    assert '"gaff[ecosistema] @ file://' in lineas[1]


def test_overrides_apuntan_a_la_rueda_de_cada_herramienta(paquete, monkeypatch):
    vistos = {}

    def run(comando):
        overrides = Path(comando[comando.index("--overrides") + 1])
        vistos[comando[-1].split(" @ ")[0]] = overrides.read_text(encoding="utf-8")
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(offline.shutil, "which", lambda nombre: "/usr/bin/" + nombre)
    monkeypatch.setattr(offline.subprocess, "run", run)
    assert offline.instalar_desde_archivo(paquete) == 0
    assert "ruedas/yutani-0.1.0" in vistos["hal"] and "ruedas/gaff/yutani-0.1.0" in vistos["gaff[ecosistema]"]
    assert all(l.split(" @ ")[1].startswith("file://") for l in vistos["hal"].splitlines())


def _reescribir(origen: Path, destino: Path, cambiar) -> Path:
    with tarfile.open(origen) as entrada, tarfile.open(destino, "w:gz") as salida:
        for miembro in entrada.getmembers():
            contenido = entrada.extractfile(miembro).read() if miembro.isfile() else None
            miembro, contenido = cambiar(miembro, contenido)
            if miembro is not None:
                salida.addfile(miembro, io.BytesIO(contenido) if contenido is not None else None)
    return destino


def test_un_archivo_alterado_cancela_todo(paquete, tmp_path, monkeypatch):
    def alterar(miembro, contenido):
        if miembro.name.endswith("hal-0.2.0-py3-none-any.whl"):
            contenido = b"otra cosa"
            miembro.size = len(contenido)
        return miembro, contenido

    alterado = _reescribir(paquete, tmp_path / "alterado.tar.gz", alterar)
    monkeypatch.setattr(offline.subprocess, "run", lambda *a, **k: pytest.fail("no debería instalar nada"))
    with pytest.raises(offline.ErrorDePaquete, match="alterado.*hal-0.2.0"):
        offline.instalar_desde_archivo(alterado)


def test_rechaza_archivos_de_mas_rutas_peligrosas_y_otra_plataforma(paquete, tmp_path):
    with tarfile.open(paquete) as tar:
        datos = json.load(tar.extractfile("paquete/paquete.json"))
    sobra = tmp_path / "sobra.tar.gz"
    with tarfile.open(paquete) as entrada, tarfile.open(sobra, "w:gz") as salida:
        for m in entrada.getmembers():
            salida.addfile(m, entrada.extractfile(m) if m.isfile() else None)
        extra = tarfile.TarInfo("paquete/ruedas/troyano-1.0-py3-none-any.whl")
        extra.size = 1
        salida.addfile(extra, io.BytesIO(b"x"))
    with pytest.raises(offline.ErrorDePaquete, match="sobran.*troyano"):
        offline.instalar_desde_archivo(sobra, simular=True)

    peligroso = tmp_path / "peligroso.tar.gz"
    with tarfile.open(peligroso, "w:gz") as salida:
        m = tarfile.TarInfo("../afuera.txt")
        m.size = 1
        salida.addfile(m, io.BytesIO(b"x"))
    with pytest.raises(offline.ErrorDePaquete, match="no permitida"):
        offline.instalar_desde_archivo(peligroso, simular=True)

    def otra_plataforma(miembro, contenido):
        if miembro.name == "paquete/paquete.json":
            contenido = json.dumps({**datos, "plataforma": "win-amd64"}).encode()
            miembro.size = len(contenido)
        return miembro, contenido

    with pytest.raises(offline.ErrorDePaquete, match="win-amd64"):
        offline.instalar_desde_archivo(_reescribir(paquete, tmp_path / "otra.tar.gz", otra_plataforma), simular=True)


def test_descarga_verificada(tmp_path, monkeypatch):
    def descargar(url, destino):
        destino.write_bytes(b"ripley" if url.endswith(".pyz") else SUMAS.encode())

    monkeypatch.setattr(offline, "_descargar", descargar)
    SUMAS = f"{offline.hashlib.sha256(b'ripley').hexdigest()}  ripley.pyz\n"
    offline.descargar_verificado("https://x/latest/download/ripley.pyz", tmp_path / "ripley.pyz")
    assert (tmp_path / "ripley.pyz").read_bytes() == b"ripley" and not (tmp_path / "ripley.pyz.SHA256SUMS").exists()
    SUMAS = "0" * 64 + "  ripley.pyz\n"
    with pytest.raises(offline.ErrorDePaquete, match="no coincide"):
        offline.descargar_verificado("https://x/latest/download/ripley.pyz", tmp_path / "ripley.pyz")
    assert not (tmp_path / "ripley.pyz").exists()


def test_mother_pyz_del_paquete_arranca(tmp_path):
    destino = offline._mother_pyz(tmp_path / "mother.pyz")
    res = subprocess.run([sys.executable, str(destino), "--version"], capture_output=True, text=True)
    assert res.returncode == 0 and res.stdout.startswith("mother ")


def test_cli(paquete, tmp_path, capsys):
    ruta = tmp_path / "ecosistema.toml"
    ruta.write_text(textwrap.dedent(MANIFIESTO), encoding="utf-8")
    assert cli.main(["--manifiesto", str(ruta), "instalar", "--desde-archivo", str(paquete), "--simular"]) == 0
    assert cli.main(["--manifiesto", str(ruta), "instalar", "--desde-archivo", str(tmp_path / "no.tar.gz")]) == 2
    (tmp_path / "roto.tar.gz").write_bytes(b"no es un tar")
    assert cli.main(["--manifiesto", str(ruta), "instalar", "--desde-archivo", str(tmp_path / "roto.tar.gz")]) == 1
    assert "no es un .tar.gz legible" in capsys.readouterr().err
