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

DevFlight usa la fuente RawTree compartida para observar los agentes que construyen el reto principal y para investigar sus resultados.

1. **Ingesta declarada:** exportadores OTLP y SDK envían metadatos de las operaciones que realmente emiten. No se promete capturar actividad privada, todas las herramientas ni sesiones anteriores.
2. **Fuente común:** el dashboard integra las tablas compatibles y los históricos autorizados. Los usuarios del mismo espacio pueden ver las estadísticas globales, con identidades de origen explícitas y límites de cobertura.
3. **Investigación por IA:** Helmcode elige consultas estructuradas sobre actividad, errores, consumo, sesiones o experimentos. RawTree devuelve la evidencia; el modelo formula hallazgos e incertidumbres a partir de esos resultados.
4. **Acción y verificación:** el usuario puede aprobar una vista privada de seguimiento desde la investigación. La aplicación la consulta y registra creación/verificación mediante el outbox. No se declara una acción exitosa cuando la consulta ha fallado.
5. **Memoria observable:** se conservan pregunta, alcance, consultas SQL, resultados, progreso y consumo reportado. La conversación permite preguntas posteriores con contexto acotado. Los reintentos HTTP no relanzan una inferencia ya aceptada.
6. **Decisiones sobre el reto principal:** el analista y la pestaña Experimentos pueden utilizar las evaluaciones agregadas del proyecto Qualcomm, indicando cuándo faltan datos para comparar variantes.

El funcionamiento depende de una conexión real a RawTree y de un modelo Helmcode autorizado. Los errores y estados parciales se muestran. La cola local conserva los eventos aceptados y sus reintentos; los límites de capacidad y deduplicación están documentados.

La captura no es indiscriminada: el esquema normalizado omite prompts, argumentos completos y razonamiento privado. Los desconocidos permanecen desconocidos y no se inventan costes ni identidades.

[Guía de implementación y comprobación](SHARED_SOURCE_AND_ANALYST.md) · [Recorrido de demo](DEMO.md).
