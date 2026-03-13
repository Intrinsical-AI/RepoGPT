
Estado v1:
- alcance congelado en `Py + Md`
- esquema congelado en `schema_version = "1"`
- `JSON` y `NDJSON` ya representan fallos parciales
- IDs y paths deben seguir siendo estables

Pendiente después de estabilización:
1. snapshots/golden más amplios por parser
2. enriquecer parser Python con más semántica sólo si no rompe esquema
3. añadir proyecciones/vistas, no plugins genéricos aún
4. caching e incremental sólo cuando el contrato esté firme
