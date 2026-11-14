# Best agentic use of RawTree - Side challenge

Fuente: `RawTree - Side challenge.pdf`, entregado por la organizacion.

## Que es RawTree

RawTree es una base de datos analitica OLAP sin esquema previo para agentes y humanos. Acepta eventos JSON, ficheros o URLs; crea tablas en el primer insert y deja que aparezcan campos nuevos a medida que evolucionan los datos.

Los campos no declarados se guardan como datos crudos y se exponen como paths SQL. Una misma ruta puede contener valores de tipos distintos entre eventos. Esta propiedad es esencial para telemetria de agentes, donde una herramienta puede devolver texto, numeros, arrays, objetos, errores o binarios representados como artefactos.

Interfaces disponibles:

- CLI `rtree`.
- API HTTP: insercion JSON y consultas SQL.
- SDK TypeScript `@rawtree/sdk`.
- OpenTelemetry mediante `@rawtree/otel` y OTLP.
- Servidor MCP alojado.

RawTree recibe OTLP en `/otlp/v1/traces`, `/otlp/v1/logs` y `/otlp/v1/metrics`; las trazas quedan aplanadas en filas SQL.

## Arranque indicado por RawTree

- CLI: instalar con `curl -fsSL https://rawtree.com/install.sh | bash`, iniciar sesion con `rtree login`, insertar con `rtree insert --table events --file ./events.jsonl` y consultar con `rtree query "SELECT ..."`. Anadir `--json` para salida consumible por una IA.
- API HTTP: base `https://api.rawtree.com`, con API key bearer. `POST /v1/tables/{table}` ingiere JSON y `POST /v1/query` ejecuta SQL.
- SDK TypeScript: `@rawtree/sdk` para insercion, consulta y metadatos; `@rawtree/otel` para OTel y trazas de AI SDK.
- MCP alojado: conectar el cliente MCP a `https://mcp.rawtree.com/mcp` e iniciar sesion con OAuth; no requiere clave ni proceso local.
- Skill para agentes: `npx skills add rawtreedb/agent-skills` instala patrones de CLI, API, SQL y manejo de errores.

## El reto

Usar RawTree en cualquier proyecto y demostrar el **mejor uso agentic de RawTree**: una IA o equipo de IAs que dependa de RawTree para almacenar, analizar y actuar sobre datos.

El agente debe ser protagonista, no un wrapper de una base de datos. Debe decidir que ingerir, que preguntas hacer y que hacer con las respuestas.

Ejemplos propuestos por la organizacion:

- Agente que carga un dataset, lo explora con SQL y explica hallazgos.
- Analista que crea y mantiene sus propias analiticas cuando llegan datos nuevos.
- Agente que guarda sus llamadas, trazas y costes y consulta su historia para mejorar.
- Agente de monitorizacion que observa un flujo de eventos y reacciona a cambios.

## Criterios de valoracion

1. **Creatividad**: idea original o uso inesperado de RawTree.
2. **Problema real**: usuario y beneficio claros.
3. **Uso agentic de RawTree**: el agente conduce la ingesta, consulta y decision mediante CLI, API, SDK o MCP.
4. **Narrativa y demo claras**: problema, solucion, encaje de RawTree y funcionamiento visible.

Un proyecto pequeno con una historia excelente puede puntuar mejor que uno grande y dificil de seguir.

## Entrega

Antes de la fecha limite, compartir un repositorio de codigo con README que explique el caso de uso, como el agente usa RawTree y como se ejecuta. Adjuntar una demo breve o historia: demo en vivo, video corto o diapositivas. Si el proyecto participa en un reto principal, basta con anadir la seccion RawTree a la misma entrega.

## Cómo DevFlight responde al reto

DevFlight convierte a **RawTree en el cerebro de observabilidad central de todos los agentes de desarrollo** que construyen el proyecto de Qualcomm:

1. **Ingesta universal e indiscriminada:** Captura toda la actividad de los agentes de programación (Claude Code, Codex, scripts) mediante OpenTelemetry (OTLP) y la API/MCP de RawTree, sin importar quién los invoque o qué tareas ejecuten.
2. **Explotación de la naturaleza OLAP sin esquema de RawTree:** Como las distintas herramientas y modelos de IA generan estructuras de datos heterogéneas (diferentes atributos, llamadas a herramientas, tokens, errores), RawTree es la solución idónea al ingerir JSONs sin esquema rígido previo y exponerlos como rutas SQL en tiempo real.
3. **Resiliencia y Privacidad (Local-First):** Redacción automática de secretos en memoria antes de persistir y buffering durable en disco que permite seguir programando offline sin perder un solo evento.
4. **Almacenamiento preparado para análisis posterior (Sin IA interna):** No se introducen agentes de IA adicionales para procesar los datos; el valor reside en consolidar la telemetría masiva en RawTree para que a posteriori analistas humanos o dashboards (como Crux) puedan auditar con SQL picos de consumo, costes por desarrollador y sesiones anómalas.
5. **Conexión mediante MCP:** Los desarrolladores pueden consultar interactivamente la telemetría de RawTree directamente desde el chat de sus agentes de codificación utilizando el servidor MCP oficial de RawTree.
