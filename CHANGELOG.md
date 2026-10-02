# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/);
versiones según [SemVer](https://semver.org/lang/es/).

## [0.2.0] - 2026-10-02

### Agregado

- **cli**: ayuda y errores de argparse en español (N-ECO-14) (`aec09ad`)

### Corregido

- **doctor**: no consultar el doctor de mother desde el de mother (`8835c0f`)
- **manifiesto**: descargarlo del repo en que se publica p1-tools (INGCOM-UNRN-P1/toolbox) (`690f9c3`)
- **windows**: ejecutar la ruta que encontró shutil.which y hacer portables los tests (`51ccc6a`)
- **herramientas**: pedirles la salida en UTF-8 y leerla así (`f46fff6`)
- **salida**: escribir en UTF-8 para no fallar con la salida redirigida en Windows (`7c8b99d`)

### Documentación

- **readme**: limitaciones, códigos de salida y salida JSON (N-ECO-09) (`54f144b`)
- **readme**: referencia generada de requisitos, opciones y comandos (N-ECO-09) (`47c9854`)

### Mantenimiento

- **ecosistema**: sincronizar manifiesto con cambios de toolbox (`530bdbf`)
- **zipapp**: usar la copia incluida de ecosistema.toml si toolbox no está disponible (`1568042`)
- **cli**: aceptar las opciones de argparse con o sin comillas (`581889c`)
- **manifiesto**: actualizar la copia incluida de ecosistema.toml (`6dde63a`)

## [0.1.1] - 2026-09-28

### Corregido

- **manifiesto**: no rechazar tipos ni estados que esta versión no conoce (`8c23c48`)

## [0.1.0] - 2026-09-28

### Agregado

- Comandos `listar`, `instalar`, `actualizar`, `doctor`, `versiones`, `autoprueba`
  y `sistema` sobre el manifiesto `ecosistema.toml` de p1-tools.
- Instalación siempre desde git (`uv tool install git+https://…`), con extras y
  con el campo `ref` del manifiesto para fijar tag o commit.
- Manifiesto desde ruta, URL, caché o copia incluida (funciona sin red).
- Zipapp `mother.pyz` sin dependencias (`scripts/construir_zipapp.py`).
