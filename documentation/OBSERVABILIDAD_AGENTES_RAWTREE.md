# Proyecto: Observabilidad de agentes de IA con RawTree

## Idea

Construir una plataforma para centralizar y analizar la telemetría generada por **Claude Code y Codex** cuando muchos desarrolladores utilizan agentes y subagentes de IA. Los eventos pueden llegar en grandes volúmenes, con estructuras distintas y sin orden previo.

**Problema:** una empresa con cientos de desarrolladores no sabe con precisión cuánto consumen sus agentes, dónde se concentran los costes ni qué patrones de uso son anómalos.

**Solución:** ingerir los eventos en **RawTree (Tinybird)** y consultarlos con SQL para extraer estadísticas útiles, sin exigir un esquema rígido antes de recibirlos.

## Arquitectura

`Claude Code / Codex → OpenTelemetry (y/o hooks) → RawTree → consultas SQL → analíticas` 

- **OpenTelemetry:** captura métricas y eventos (tokens, costes, modelos, sesiones, subagentes, errores y picos de actividad, según la información disponible).
- **RawTree:** recibe eventos semiestructurados, los almacena y permite consultarlos y agregarlos.
- **Capa analítica:** transforma los datos en indicadores y conclusiones. **No hace falta machine learning, RAG ni otro LLM.**
- **MCP (opcional):** permite a Claude Code o Codex consultar las estadísticas mediante herramientas; no sustituye al mecanismo de recolección de telemetría.

Conviene incluir `timestamp`, `developer_id`, `session_id`, `agent_id` y `model` para correlacionar eventos, evitar dobles contabilizaciones entre agentes y subagentes y no ingerir prompts ni código sensible innecesariamente.

## Qué analizar

- Consumo de tokens y coste por desarrollador, modelo, sesión y agente.
- Subagentes que concentran el gasto.
- Picos temporales de actividad y consumo.
- Sesiones con costes o patrones de uso anómalos.
- Evolución del uso y posibles oportunidades de optimización.

El objetivo no es solo almacenar logs, sino **responder preguntas que permitan tomar decisiones**, por ejemplo qué agentes conviene revisar o dónde se desperdician recursos.

## Demostración mínima para la Datathon

1. Generar o capturar sesiones reales de Claude Code / Codex.
2. Enviar los eventos a RawTree mediante OpenTelemetry o un colector compatible.
3. Ejecutar consultas SQL que produzcan métricas y comparaciones.
4. Mostrar al menos una conclusión accionable, como un subagente con gasto inusualmente alto.

Una historia breve es suficiente: *«Una empresa con cientos de programadores utiliza agentes de IA, pero carece de visibilidad centralizada sobre su coste y comportamiento. Nuestro sistema convierte su telemetría en decisiones».*

## Extensión opcional: dashboard para el side challenge **Crux**

**Si queda tiempo**, conectar estas analíticas a un dashboard de calidad (por ejemplo, una web app, Power BI, Shiny o Tableau), con indicadores bien seleccionados, gráficas adecuadas y conclusiones explícitas. Los jueces valoran:

- **Utilidad para tomar decisiones:** qué preguntas resuelve y qué decisiones fundamenta.
- **Adecuación:** si las representaciones corresponden a los datos y comparaciones.
- **Coherencia:** si indicadores, gráficos y conclusiones son consistentes entre sí.

**Restricción importante:** el enunciado de Crux pide que el dashboard ayude a tomar decisiones sobre el **reto principal del equipo (Qualcomm)**. Como este proyecto de telemetría es independiente, **un dashboard de sus métricas no encaja automáticamente en Crux**. Para presentarlo allí habría que vincular sus indicadores a decisiones reales del reto de Qualcomm o confirmar con la organización que aceptan proyectos independientes.

**Prioridad:** primero una canalización funcional de extremo a extremo; después consultas útiles; finalmente, el dashboard si el tiempo y las reglas del side challenge lo permiten.
