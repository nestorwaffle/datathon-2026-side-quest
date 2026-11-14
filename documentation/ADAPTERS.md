# Adaptadores, Conexiones y Límites Observables

**Uso vigente:** `fme-trace collect` es el receptor dedicado con sincronización periódica; `fme-trace run` sincroniza al terminar (salvo `--no-sync`). Ver [TELEMETRY_QUICKSTART.md](TELEMETRY_QUICKSTART.md) para identificación de desarrolladores, sesiones y configuración real de cada proveedor. El MCP no activa captura automática.

## 1. Conexión de Agentes de Desarrollo con RawTree mediante MCP

Los desarrolladores del proyecto Qualcomm que utilicen **Claude Code, Cursor o Codex** pueden conectar sus entornos de programación directamente a RawTree a través de su servidor **MCP (Model Context Protocol)**:
- **Endpoint MCP alojado:** `https://mcp.rawtree.com/mcp`
- **Autenticación:** OAuth o API Key Bearer.
- **Capacidades:** Permite a los programadores ejecutar consultas SQL interactivas sobre los datos de telemetría directamente desde el chat de su agente de desarrollo, sin salir de su editor o terminal.
- **Rol en el proyecto:** El MCP es una interfaz de consulta y trabajo; no reemplaza el pipeline de recolección de telemetría automática que realiza OpenTelemetry hacia la cola durable y RawTree.

---

## 2. Adaptador para Codex

Usar `codex exec --json` a través de `fme-trace run --source codex`. El importador consume JSONL:
- `item.started`/`item.completed` con `command_execution`, `mcp_tool_call` o `web_search` se convierten en eventos tool.
- `agent_message` se registra como respuesta visible del agente.
- `file_change` es referencia de cambio de archivo.
- `turn.completed` conserva el desglose de tokens (`usage`).
- `turn.failed`/`error` registran excepciones y fallos.
- El registro original se conserva íntegro bajo `data.record`, sujeto al filtro de redacción de secretos.

Referencia oficial: https://developers.openai.com/codex/noninteractive/

---

## 3. Adaptador para Claude Code

Usar `claude -p ... --output-format stream-json --verbose`.
- Se conservan mensajes `user`/`assistant` y resultados de ejecución.
- Los bloques `tool_use` y `tool_result` generan eventos de herramienta con su ID, argumentos y respuestas.
- Para relaciones causales completas entre agentes y subagentes se usa el SDK `Trace.child` o la propagación de contexto en variables de entorno (`DEVFLIGHT_TRACE_ID`, `DEVFLIGHT_SPAN_ID`).

Referencia oficial: https://code.claude.com/docs/en/headless

---

## 4. Adaptador Universal OpenTelemetry (OTLP / HTTP JSON)

Cualquier herramienta o agente compatible con OpenTelemetry puede volcar su telemetría directamente al colector local:
- **Configuración requerida:**
  ```sh
  export OTEL_EXPORTER_OTLP_PROTOCOL="http/json"
  export OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:8787"
  ```
- **Endpoints del receptor local:**
  - `/v1/traces`: recibe spans y árboles de ejecución.
  - `/v1/logs`: recibe eventos y registros de depuración.
  - `/v1/metrics`: recibe contadores y mediciones de consumo.
- **Reenvío a RawTree:** Al ejecutar `fme-trace sync`, estos datos se envían a los endpoints nativos OTLP de RawTree (`/otlp/v1/traces`, `/otlp/v1/logs`, `/otlp/v1/metrics`), aplanándose automáticamente en filas SQL dentro de RawTree.

Referencia oficial: https://rawtree.com/docs/integrations/opentelemetry

---

## 5. Privacidad y Límites Operativos

- **Redacción de secretos:** El redactor reconoce tokens Bearer, passwords, cookies, y formatos de API keys (`sk-*`, `rt_*`, `ghp_*`, etc.). Los atributos sensibles de OpenTelemetry se redactan también en la representación `{key, value}`.
- **Buffering local:** Cada evento se escribe en JSONL local antes de intentar cualquier sincronización de red. Si se corta la conexión o se trabaja offline, la cola conserva todos los eventos intactos.
- **Sin modelos internos:** Este sistema no ejecuta inferencia de IA para clasificar o procesar eventos. La telemetría se almacena cruda y fiel para su explotación analítica posterior.
