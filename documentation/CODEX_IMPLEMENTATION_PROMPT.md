# Prompt para Codex - implementar DevFlight y el Math Copilot

> Nota de alcance (14/11/2026): este prompt conserva instrucciones históricas de Analyst y Arduino. Para la fase vigente prevalecen `OBSERVABILIDAD_AGENTES_RAWTREE.md`, `DEVFLIGHT_IMPLEMENTATION_PLAN.md` y la petición del usuario: solo captura de telemetría e ingesta en RawTree. No ejecutar las fases de analista, políticas, dashboard o copilot. Uso actual: `TELEMETRY_QUICKSTART.md`.

Pega el siguiente prompt completo en una nueva tarea de Codex con el directorio de trabajo `C:\Users\miasi\Documents\DATATHON`.

---

Eres el agente principal de implementacion del proyecto Datathon FME 2026. Debes construir el sistema completo descrito en la documentacion del repositorio, con prioridad en entregar una demo funcional, verificable y ganadora del side challenge de RawTree sin romper el reto principal de Qualcomm.

## Regla de inicio obligatoria

Antes de ejecutar, crear, editar o borrar ningun fichero, lee completos estos documentos y obedece sus decisiones:

1. `documentation/README.md`
2. `documentation/QUALCOMM_MAIN_CHALLENGE.md`
3. `documentation/RAWTREE_SIDE_CHALLENGE.md`
4. `documentation/DEVFLIGHT_IMPLEMENTATION_PLAN.md`

Despues, inspecciona el repositorio real, sus cambios existentes, sus configuraciones y las herramientas disponibles. No sobrescribas trabajo existente. Si la documentacion y el estado real discrepan, conserva el trabajo existente, explica la discrepancia y adapta la implementacion de manera compatible.

## Objetivo de producto

Construye **DevFlight**, una plataforma de telemetria agentic para el equipo. Debe capturar de forma completa todo dato observable de las IAs, agentes y subagentes utilizados para crear, entrenar, evaluar, depurar o disenar el Math Copilot de Qualcomm.

DevFlight debe:

- Capturar prompts y respuestas visibles, arboles de agentes, tool calls, argumentos, resultados, errores, stdout, stderr, comandos, diffs, ficheros, skills, RAG, UI, eventos de Arduino, tokens, costes y evaluaciones.
- Persistir primero en local; no perder datos sin red ni si RawTree responde con timeout.
- Sincronizar por lotes con RawTree y mantener trazabilidad completa por `run_id`, `trace_id`, `span_id`, `parent_span_id`, `event_id` y `artifact_id`.
- Aceptar datos de cualquier IA y framework: CLI/API generica, Python, HTTP/JavaScript y OpenTelemetry.
- Usar RawTree como memoria cruda heterogenea y no como un simple dashboard.
- Centralizar la telemetría en RawTree para que a posteriori se explote con consultas SQL y dashboards analíticos (sin requerir agentes de IA analistas adicionales dentro del proyecto).

El reto Qualcomm debe proporcionar dos experiencias offline en Arduino UNO Q:

- `Study / Teach`: ayuda socratica breve que no revele respuesta ni opcion correcta.
- `Challenge / Reason`: devuelve A-E para evaluar M3Kang.

El Arduino debe funcionar sin internet y sin una clave de RawTree.

## Orden de trabajo obligatorio

1. Presenta una lista corta de los documentos leidos, el estado que encontraste y un plan por fases que respete `DEVFLIGHT_IMPLEMENTATION_PLAN.md`.
2. Implementa primero una vertical completa y demostrable:
   - contrato de eventos;
   - redactor de secretos;
   - cola JSONL local;
   - CLI `fme-trace run`, `emit`, `sync` y `status`;
   - uploader a `dev_events_raw` de RawTree;
   - prueba de recuperacion de un evento completo.
3. Anade SDK Python y envuelve el flujo de evaluacion/Qwen/RAG/skills que exista realmente en el repositorio.
4. Anade captura de artefactos, diffs y blobs fragmentados/deduplicados.
5. Anade adaptadores de CLI/importacion para Codex y Claude usando formatos estructurados documentados. Declara con precision los limites de cada adaptador; no inventes telemetria que el proveedor no expone.
6. Anade endpoint/SDK HTTP para UI y otros lenguajes, y OTLP para procesos que ya emitan OpenTelemetry.
7. Implementa DevFlight Analyst con consultas RawTree, `eval.grade`, `decision.candidate` y `decision.promoted`.
8. Integra el modo offline del Arduino y deja un guion reproducible de la demo.

Tras cada fase, ejecuta las pruebas pertinentes, informa de lo que funciona y continua con la siguiente fase. No te limites a escribir codigo: verifica la insercion, consulta y recuperacion reales en RawTree cuando haya credenciales disponibles.

## Contrato tecnico minimo

No cambies estos nombres ni campos sin actualizar toda la documentacion y los tests:

```json
{
  "schema_version": 1,
  "event_id": "uuid-v7",
  "timestamp": "RFC3339 UTC",
  "project_id": "datathon-mathops",
  "run_id": "uuid-v7",
  "trace_id": "hex",
  "span_id": "hex",
  "parent_span_id": "hex-or-null",
  "sequence": 42,
  "agent": {"id": "agent-name", "framework": "cli", "model": "provider/model"},
  "task": {"id": "task-id", "kind": "skill_authoring"},
  "event_type": "tool.result",
  "status": "ok",
  "data": {},
  "artifacts": []
}
```

Tipos minimos: `run.started`, `run.finished`, `agent.spawned`, `agent.finished`, `llm.request`, `llm.response`, `tool.started`, `tool.result`, `command.finished`, `skill.invoked`, `rag.retrieved`, `ui.action`, `board.event`, `artifact.created`, `eval.grade`, `decision.candidate`, `decision.promoted`, `error`.

Usa las tablas `dev_events_raw`, `dev_artifacts_raw`, `dev_traces`, `dev_logs` y `dev_metrics`. Conserva `data` crudo y heterogeneo: RawTree debe recibir la forma original, no una version prematuramente normalizada.

## Fiabilidad, seguridad y datos

- Todo evento se escribe localmente antes de subirlo.
- Conserva el segmento local hasta confirmacion de RawTree.
- Usa `event_id` y token de deduplicacion estable por lote; los reintentos no pueden crear nuevos IDs.
- Redacta API keys, passwords, cookies, JWTs y tokens antes de disco o red.
- Conserva datos completos de desarrollo salvo secretos. No intentes ni afirmes guardar razonamiento privado oculto.
- No pongas credenciales en codigo, logs, prompts, commits o Arduino. Usa variables de entorno y `.env.example` sin valores.
- No borres ninguna base o tabla RawTree hasta identificarla, mostrar recuentos y tener autorizacion expresa para ese objetivo exacto.

## DevFlight Analyst

El analista debe ser protagonista del uso de RawTree:

1. Leer eventos, trazas y evaluaciones desde RawTree mediante API/SQL/MCP con permiso de solo lectura.
2. Comparar tasa de exito, exactitud, P50/P95 de tiempo, tokens, errores de tools y coste por `task.kind`, modelo, agente, prompt, skill y estrategia RAG.
3. Crear una receta candidata con agente, modelo, prompt base, skill, herramientas y presupuesto.
4. Promover automaticamente una receta solo con tres ejecuciones comparables como minimo, mejor tasa de exito que el champion y menor mediana de tiempo/tokens en empate.
5. Promover un `policy-pack` de Arduino solo si no baja exactitud M3Kang, no revela solucion/opcion en pruebas socraticas y no aumenta P95 mas de 5%.
6. Registrar toda conclusion, SQL usado, evidencia, champion anterior y decision final como eventos `decision.*`.

No uses RawTree solo para mostrar tablas. La demo debe hacer visible una decision que cambie una ejecucion posterior o una policy del Arduino.

## Criterios de aceptacion obligatorios

No declares el trabajo terminado hasta demostrar:

- Una ejecucion padre-hijo con tool, RAG, skill, evaluacion y fichero modificado se reconstruye por `trace_id`.
- Prompt, output, tool args/result, stdout, stderr y artefacto se recuperan completos; una clave de prueba aparece redactada.
- `data.value` acepta tipos mezclados sin migracion ni perdida.
- Una caida de red o timeout no pierde eventos ni duplica logicamente un `event_id` despues de `sync`.
- DevFlight Analyst compara al menos tres ejecuciones y promueve una receta con evidencia.
- Study y Challenge funcionan sin red en la ruta de ejecucion del Arduino o, si no hay placa conectada, mediante una prueba de integracion reproducible que documente claramente el limite de hardware.
- README y guia de demo explican instalacion, variables de entorno, comandos para cada companero y recuperacion ante offline.

## Forma de trabajar

- Haz cambios pequenos, comprobables y compatibles con el estado actual del repositorio.
- Antes de cambios destructivos, inspecciona objetivos exactos y conserva datos ajenos.
- Manten la documentacion sincronizada con el codigo y anota limitaciones reales.
- Si faltan credenciales RawTree, implementa modo local y pruebas simuladas sin bloquear; deja un unico paso claro de configuracion para conexion real.
- Al final, entrega un resumen con ficheros modificados, comandos de verificacion ejecutados, resultados, pendientes reales y el guion exacto para la demo.

---
