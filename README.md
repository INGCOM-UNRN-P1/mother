# mother — instalador y diagnóstico del ecosistema de Programación 1

_(MU/TH/UR 6000, la computadora de la Nostromo.)_

Instala, actualiza y diagnostica las herramientas del ecosistema **siempre
desde git** (varios nombres de paquete están tomados en PyPI por proyectos
ajenos). Lee el manifiesto único `ecosistema.toml` de
[p1-tools](https://github.com/INGCOM-UNRN-P1/p1-tools) y reemplaza a
`clone_repos.sh`, `install_tools.sh` y `health_check.sh`.

No tiene dependencias: solo necesita Python ≥ 3.11 y
[uv](https://docs.astral.sh/uv/getting-started/installation/). Se distribuye
también como un único archivo, `mother.pyz`.

## Instalación

```bash
uv tool install git+https://github.com/INGCOM-UNRN-P1/mother
```

o, sin instalar nada, con el zipapp del último release:

```bash
python3 mother.pyz instalar --perfil estudiante
```

## Uso

| Comando | Qué hace |
|:--|:--|
| `mother listar [--perfil P]` | Herramientas del manifiesto y si están instaladas |
| `mother instalar --perfil P` / `--todo` | `uv tool install git+https://…` de cada herramienta del perfil (`--simular` muestra los comandos; `--forzar` reinstala) |
| `mother actualizar [--perfil P]` | `uv tool upgrade` de las herramientas instaladas |
| `mother doctor [--perfil P] [--json]` | Diagnóstico agregado: Python, uv, git y el `doctor --json` de cada herramienta; sale con 1 si falta algo requerido |
| `mother versiones [--perfil P] [--json]` | Versión instalada de cada herramienta frente a la esperada por el manifiesto |
| `mother autoprueba [--perfil P] [--json]` | Verifica el contrato de línea de comandos (`-h`, `--version`, `doctor --json`) de lo instalado |
| `mother sistema [--perfil P]` | Programas del sistema que necesita el perfil (gcc, gdb, valgrind…) |

Perfiles: `estudiante`, `analisis`, `docente`, `contenido`, `aula`.

### De dónde sale el manifiesto

1. `--manifiesto RUTA|URL`, o la variable `MOTHER_MANIFIESTO`;
2. el publicado en p1-tools (se guarda en `~/.cache/mother/`);
3. sin red (`--sin-red` o sin conexión): la última copia en caché;
4. si no hay caché: la copia incluida en mother al construirlo.

## Desarrollo

```bash
uv sync
uv run pytest -q
python3 scripts/construir_zipapp.py --manifiesto ../p1-tools/ecosistema.toml   # dist/mother.pyz
```

## Licencia

GPL-3.0-or-later (ver `LICENSE`).
