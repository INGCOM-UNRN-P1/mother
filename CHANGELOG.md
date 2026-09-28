# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/);
versiones según [SemVer](https://semver.org/lang/es/).

## [0.1.0] - 2026-09-28

### Agregado

- Comandos `listar`, `instalar`, `actualizar`, `doctor`, `versiones`, `autoprueba`
  y `sistema` sobre el manifiesto `ecosistema.toml` de p1-tools.
- Instalación siempre desde git (`uv tool install git+https://…`), con extras y
  con el campo `ref` del manifiesto para fijar tag o commit.
- Manifiesto desde ruta, URL, caché o copia incluida (funciona sin red).
- Zipapp `mother.pyz` sin dependencias (`scripts/construir_zipapp.py`).
