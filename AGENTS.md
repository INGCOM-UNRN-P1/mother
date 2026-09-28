# Instrucciones para el Agente (mother)

1. **Commits semánticos en español**: `<tipo>(<alcance>): <descripción>`.
2. **Sin dependencias**: mother corre antes que cualquier otra herramienta y se
   distribuye como zipapp; solo biblioteca estándar (Python ≥ 3.11).
3. **Nunca instalar por nombre**: todo requisito es `git+https://…` (con
   `paquete[extras] @ git+…` cuando hay extras).
4. El manifiesto es el de p1-tools: mother no mantiene listas propias de herramientas.
