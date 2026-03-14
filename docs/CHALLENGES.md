## **Aspectos a Considerar / Posibles Desafíos**

* **Soporte de Lenguajes:**
  En el corto plazo el foco es `Py + Md`. Cualquier lenguaje adicional sólo entra cuando tenga parser, tests y contrato de salida al mismo nivel de estabilidad.

* **Complejidad de Implementación de "Vistas" (Views/Projections):**
  ¿Cuán sencillo será para un usuario definir una “vista” personalizada del código (por ejemplo: solo imports, solo clases, funciones + docstrings, etc)?

  * **Por código:** Gran flexibilidad, pero barrera de entrada para usuarios menos técnicos.
  * **Por configuración/DSL:** Más accesible, pero requiere diseño y parsing adicional.
  * *Decisión clave*: equilibrar flexibilidad con facilidad de uso.

* **Rendimiento:**
  Analizar grandes repositorios puede ser intensivo en tiempo y memoria, especialmente si se hacen múltiples pases (parseo, procesado, reporte). Será importante:

  * Optimizar recorridos de árbol,
  * Cachear resultados intermedios,
  * Ofrecer modos “rápido” vs. “completo”.

* **Madurez y Calidad de los Parsers:**
  Toda la calidad de la extracción depende de los parsers (AST, tokenización, heurística).

  * Para Python hay soporte nativo en la stdlib. Markdown requiere heurística propia y golden tests para no degradar el árbol.
  * El parser debe estar muy probado con “edge cases” reales (véase la carpeta de fixtures).

* **Competencia / Alternativas:**
  Existen herramientas avanzadas (ctags, tree-sitter, linters, análisis estático, docgenerators, IDEs) que cubren partes de este problema.

  * **Diferenciación de RepoGPT:** la unificación de análisis, la salida estructurada y consultable, y el enfoque explícito en LLM/RAG y la extensibilidad.

* **Casos de Uso Potenciales (más allá de LLMs):**

  * Generación automática de documentación: esqueletos de API, resúmenes de módulos.
  * Análisis de dependencias internas y externas.
  * Detección de “code smells” o patrones a medida.
  * Refactorización asistida: entender impactos, dependencias, puntos de entrada.
  * Creación de mapas visuales, diagramas y métricas para arquitectos y devs.


## TODOs/Oportunidades de mejora

1. **Paralelización y caching**

   * Integrar procesamiento paralelo (por fichero o por nodo)
   * Cachear árboles sintácticos para repos con cambios incrementales

2. **Implementar el “Reporter”**

   * Generación de gráficos de dependencia (por ejemplo, con Graphviz)
   * Métricas de complejidad de código, tests cubiertos, ratio de comentarios

3. **UI/UX interactivo**

   * Webapp ligera con vistas filtrables (imports, TODOs, docstrings)
   * Integración con IDE sólo después de fijar el contrato del artefacto

4. **Estrategia de lanzamiento incremental**

   * Consolidar `Py + Md` antes de abrir nuevos lenguajes
   * Crear ejemplos de casos de uso concretos (RAG de código, auditorías, diffs estructurados)

5. **Ecosistema y colaboración**

   * Documentar claramente la API de adaptadores y procesadores
   * Abrir extensibilidad real sólo cuando el esquema v1 haya demostrado estabilidad
