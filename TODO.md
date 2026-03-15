
Estado v1:
- alcance congelado en `Py + Md`
- esquema congelado en `schema_version = "1"`
- `JSON` y `NDJSON` ya representan fallos parciales
- IDs y paths deben seguir siendo estables

Decisiones de diseño documentadas:
- Archivos ocultos: el collector NO filtra todo lo que empiece por `.`; usa
  DEFAULT_IGNORES explícito (`.git`, `.venv`, `__pycache__`…). Ficheros como
  `.github/workflow.py` o `.env` son colectables — filtrarlos es
  responsabilidad del `.repogptignore`.
- Exit codes: 0 = ok, 1 = fail-fast abort, 2 = parse failures parciales,
  3 = error de filesystem/ruta inválida.
- Markdown fences: se soportan `` ``` `` y `~~~`; la info string puede tener
  espacios, sólo se usa el primer token como lenguaje. Un bloque abierto con
  `` ``` `` sólo lo cierra otra línea `` ``` `` (no `~~~`, y viceversa).

Bugs corregidos (implementación baja — review pass):
- BUG-1: test-exclude usaba `"tests" in p.parts` (absoluto) → `"tests" in p.relative_to(repo_root).parts`
- BUG-2: `p.stat().st_size` sin capturar `OSError` (race condition) → try/except con skip
- BUG-3: `_python_external_ids` duplicaba el último segmento en nodos huérfanos → bucle `while True` con append al inicio
- BUG-4: `_extract_span_text` devolvía `content` (íntegro) en rango inválido → devuelve `""`
- EDGE-1/2: `FENCE_RE` no reconocía `~~~` ni info strings con espacios → regex extendida + cierre validado por delimitador
- EDGE-3: cálculo de número de línea de comentarios Markdown era O(N×M) → bisect sobre lista de offsets O(N log M)
- EDGE-4: pipeline abría el archivo dos veces (hash + decode) → lectura única de bytes con decode y hash en memoria
- COMP-1: métricas duplicadas en constructor Markdown (`heading_count`, etc.) → eliminadas del constructor
- COMP-2: `_associate_comments` recursiva → iterativa con stack explícito (evita RecursionError en árboles profundos)

Pendiente después de estabilización:
1. snapshots/golden más amplios por parser
2. enriquecer parser Python con más semántica sólo si no rompe esquema
3. añadir proyecciones/vistas, no plugins genéricos aún
4. caching e incremental sólo cuando el contrato esté firme
