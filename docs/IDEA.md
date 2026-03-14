# RepoGPT

RepoGPT produce artefactos estructurados y deterministas para `Py + Md`.

Contrato v1:
- `json`: envelope con `schema_version`, `repo_root`, `stats`, `failures`, `records`
- `ndjson`: registros `node`, `failure`, `summary`
- `path`: siempre relativo al repo
- `id`: determinista por nodo

Objetivo inmediato:
1. servir como fuente fiable para RAG y evaluación
2. exponer árboles útiles de Python y Markdown
3. reflejar fallos parciales en el artefacto, no sólo en logs
