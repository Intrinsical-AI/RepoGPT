
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

Pendiente después de estabilización:
1. snapshots/golden más amplios por parser
2. enriquecer parser Python con más semántica sólo si no rompe esquema
3. añadir proyecciones/vistas, no plugins genéricos aún
4. caching e incremental sólo cuando el contrato esté firme
