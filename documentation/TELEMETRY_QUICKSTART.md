# Fase 1: programador + IA -> RawTree

Este es el alcance vigente. El documento maestro es `OBSERVABILIDAD_AGENTES_RAWTREE.md`; las instrucciones antiguas de Analyst/Arduino del prompt original no se ejecutan en esta fase. No hay dashboard ni inferencia para analizar eventos. El código previo de esos experimentos se conserva, pero `collect`, `run`, `sync` y los SDK no lo necesitan.

## 1. Configuración por programador

Instalar Python >=3.11 y `python -m pip install -e .`. En este equipo usar `./.venv/Scripts/python.exe` y `./.venv/Scripts/fme-trace.exe`.

Configurar `.env` (ignorado por Git): `RAWTREE_API_KEY` con el **token completo**, `RAWTREE_READ_KEY` para verificación/lectura y `RAWTREE_DATABASE=datathon_mathops`. El identificador UUID de una clave no sirve como token Bearer. El cargador no sobrescribe variables ya definidas en el proceso; reiniciar el colector tras cambiar credenciales.

```powershell
$env:DEVFLIGHT_DEVELOPER_ID='guillem'
$env:DEVFLIGHT_SESSION_ID='ui-20261114-01'
./.venv/Scripts/fme-trace.exe doctor --read
```

`doctor` realiza una consulta, por lo que una clave estrictamente de escritura puede recibir 403: verificar la conexión de lectura con `--read` y la de escritura con un envío. Nunca incluir claves en los argumentos del wrapper.

## 2. Captura de Codex / Claude Code

Ejecutar desde el repositorio donde trabaja la IA (el snapshot se limita al directorio de trabajo). Si se cambia de directorio, pasar la ruta absoluta de `fme-trace.exe` o activarlo en PATH.

```powershell
fme-trace run --developer guillem --session ui-20261114-01 --agent codex --source codex --task ui-teach --kind ui_implementation -- codex.cmd exec --json "Implementa la UI de Teach siguiendo la especificacion del repositorio"
fme-trace run --developer etna --agent claude --source claude --task reason -- claude -p "Revisa los errores de este modulo" --output-format stream-json --verbose
```

En Linux el ejecutable es `codex`, sin `.cmd`. Los agentes deben estar instalados y autenticados en el equipo del desarrollador. **El wrapper sincroniza automáticamente al terminar**, también cuando falla el comando. Un error de red conserva la cola y se comunica por stderr sin cambiar el código de salida de la tarea. `--no-sync` desactiva esa subida.

Se capturan comandos, stdout/stderr completos al finalizar, registros JSON expuestos, usage, errores y archivos cambiados. Los prompts en argumentos quedan registrados; no se inventan prompts de sistema internos ni acciones que el proveedor no exporte. Usar `--model` si el stream no identifica el modelo; en ausencia de datos queda `unknown`, y costes desconocidos quedan null. Los IDs de sesión del proveedor sustituyen el ID inicial en sus eventos; `run_id` y `trace_id` vinculan todo el wrapper.

## 3. Colector continuo y OTLP

```powershell
fme-trace --home .devflight/telemetry collect --port 8787 --interval 5
```

`collect` es un receptor **solo de telemetría**, con subida periódica y sin UI/analista/copilot. Para enviar desde herramientas instrumentadas:

```powershell
$env:OTEL_EXPORTER_OTLP_PROTOCOL='http/json'
$env:OTEL_EXPORTER_OTLP_ENDPOINT='http://127.0.0.1:8787'
$env:OTEL_RESOURCE_ATTRIBUTES='developer_id=guillem,service.name=qualcomm-development'
# Claude Code requiere activar explícitamente sus exporters:
$env:CLAUDE_CODE_ENABLE_TELEMETRY='1'
$env:OTEL_METRICS_EXPORTER='otlp'
$env:OTEL_LOGS_EXPORTER='otlp'
claude
```

Estas variables no instrumentan automáticamente cualquier aplicación. Para Codex usar el wrapper JSON indicado arriba; para Cursor se requiere una exportación o un hook explícito que envíe a `/events`. No se promete observar todas las apps del ordenador. Los exporters y la captura de contenido disponible dependen de cada proveedor/versión. Referencia Claude: https://code.claude.com/docs/en/monitoring-usage

Endpoints locales: `/events`, `/v1/traces`, `/v1/logs`, `/v1/metrics`; JSON, gzip opcional, máximo 4 MiB descomprimidos. No admite protobuf/gRPC. Se conservan los atributos OTLP originales, incluso si un lote mezcla sesiones o desarrolladores. El ID de la envoltura representa recepción del lote; para spans reales utilizar traceId/spanId del payload o las tablas nativas.

```json
{"event_type":"tool.result","developer_id":"nestor","session_id":"ui-01","agent":{"id":"my-agent","model":"provider/model"},"data":{"name":"tests","result":{"passed":true}}}
```

La respuesta 201 de `/events` confirma persistencia **local**, no inserción remota. La cola y `last_error` indican si falta sincronizar. `DEVFLIGHT_HTTP_TOKEN` protege el receptor si se configura; enviar Authorization Bearer. Escucha únicamente en loopback.

## 4. Qué queda en RawTree

Base `datathon_mathops`, organización `datathon-upc-relus`, clúster `relus-cluster`:

- `dev_events_raw`: envoltura de todos los eventos, payload original y `event_json`.
- `dev_artifacts_raw`: metadatos y fragmentos gzip/base64 con SHA-256.
- `dev_traces`, `dev_logs`, `dev_metrics`: transformaciones OTLP nativas de RawTree cuando llegan esas señales.

`event_json` conserva exactamente fechas, nulls y tipos del evento redactado: la representación JSON dinámica de RawTree puede reformatear timestamps y omitir nulls. Los otros campos siguen siendo consultables directamente.

```sql
SELECT developer_id, session_id, agent_id, event_type, event_id
FROM dev_events_raw
WHERE session_id = 'telemetry-implementation-20261114'
ORDER BY timestamp, event_id LIMIT 100;

SELECT event_json AS event FROM dev_events_raw
WHERE event_json IS NOT NULL
ORDER BY timestamp DESC LIMIT 20;
```

No sumar indiscriminadamente los distintos registros de tokens: `llm.usage` es el contador canónico del adaptador (por turno Codex / resultado de sesión Claude). Datos originales también contienen usage. Las métricas OTLP pueden ser acumulativas; el analista futuro deberá considerar temporalidad y deduplicar event_id.

## 5. Verificar y recuperar

```powershell
fme-trace --home .devflight/telemetry status
fme-trace --home .devflight/telemetry sync
python scripts/telemetry_smoke.py
python scripts/rawtree_verify.py
python -m unittest discover -s tests -v
```

Los dos scripts de probe generan **datos sintéticos identificados**, no sesiones ficticias de IA. El segundo comprueba redacción y restauración de un artefacto completo remoto. Los reintentos conservan identidad y lote. La deduplicación remota depende de la ventana de RawTree; identidad lógica por event_id. Un artefacto puede haberse subido en una traza anterior: restaurar por artifact_id consultando `dev_artifacts_raw`.

## Límites de esta versión

El wrapper analiza stdio cuando acaba el comando; un cierre forzado del wrapper puede perder stdio todavía en memoria. SDK/HTTP confirman persistencia local antes de responder. El redactor filtra claves estructuradas, secretos de entorno y patrones comunes; no garantiza reconocer credenciales arbitrarias cifradas o sin etiqueta. Los snapshots capturan estado inicial/final y excluyen `.env`, claves, colas, dependencias y datos privados. La cola escanea segmentos y está orientada a la demo/equipo pequeño; para cientos de desarrolladores con millones de eventos necesita índice y archivado. No se han ejecutado sesiones externas nuevas de Claude/Cursor como prueba; su cobertura se valida con fixtures de formato.
