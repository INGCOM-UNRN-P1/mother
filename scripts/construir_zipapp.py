#!/usr/bin/env python3
"""Construye dist/mother.pyz, un único archivo ejecutable con `python mother.pyz`.

Como mother no tiene dependencias, el zipapp es solo el paquete. Con
--manifiesto se actualiza antes la copia incluida de ecosistema.toml (la que
se usa sin red y sin caché).

Uso: construir_zipapp.py [--manifiesto RUTA] [--salida dist/mother.pyz]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PAQUETE = RAIZ / "src" / "mother"


def main(argv: list[str]) -> int:
    # En Windows, con la salida redirigida, print escribe en cp1252 y no puede con «✓».
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifiesto", type=Path, help="ecosistema.toml a incluir (por defecto, el actual)")
    parser.add_argument("--salida", type=Path, default=RAIZ / "dist" / "mother.pyz")
    args = parser.parse_args(argv)

    if args.manifiesto:
        shutil.copyfile(args.manifiesto, PAQUETE / "ecosistema.toml")
    with tempfile.TemporaryDirectory() as tmp:
        fuente = Path(tmp) / "app"
        shutil.copytree(PAQUETE, fuente / "mother", ignore=shutil.ignore_patterns("__pycache__"))
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(fuente, args.salida, interpreter="/usr/bin/env python3", main="mother.cli:_principal")
    print(f"✓ {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
