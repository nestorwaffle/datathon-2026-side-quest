# DevFlight - Plan de Implementación

## 1. Objetivo y Resultado Demostrable

**DevFlight** es la plataforma de observabilidad de desarrollo del equipo. Captura de forma universal e indiscriminada el trabajo observable de cualquier IA, agente o subagente empleado por los programadores (Claude Code, Codex, Cursor, scripts) para construir el proyecto de Qualcomm; lo almacena íntegro en **RawTree (Tinybird OLAP)** mediante **OpenTelemetry (OTLP)** y una cola local durable.

### Filosofía y Alcance Preciso
- **Complemento totalmente independiente:** No forma parte del código de producción del Arduino UNO Q ni requiere conexión a internet en la placa.
- **Sin agentes de IA internos para análisis:** **Este proyecto no incluye un LLM ni agentes autónomos que analicen los datos.** No se utilizan APIs de inferencia externas (sin Helmcode ni modelos adicionales). El objetivo es almacenar un gran volumen de telemetría heterogénea en RawTree, de modo que quede disponible para que a posteriori se explote con SQL, detección de picos de uso, auditorías de costes o dashboards (como Crux).
- **Conexión mediante MCP y OpenTelemetry:** Los programadores y sus entornos (Claude Code, Codex) se conectan a RawTree usando el protocolo estándar de OpenTelemetry y el servidor MCP de RawTree.

---

## 2. Alcance de Captura y Privacidad

### Lo que se captura indiscriminadamente
- **Metadatos:** `timestamp`, `developer_id`, `session_id`, `agent_id`, `model`.
- **Interacciones:** Prompts, respuestas y mensajes visibles de los agentes.
- **Árboles de agentes y subagentes:** Relaciones padre-hijo (`trace_id`, `span_id`, `parent_span_id`).
- **Llamadas a herramientas (Tool Calls):** Nombres de herramientas, argumentos, resultados, códigos de salida, tiempos de ejecución, stdout y stderr.
- **Cambios en código y artefactos:** Ficheros creados o modificados, diffs y hashes SHA-256 de artefactos completos.
- **Consumo y rendimiento:** Tokens de prompt, tokens de respuesta, tokens en caché y latencias.
- **Errores y excepciones:** Trazas de fallos de red, timeouts y códigos de error.

### Lo que NO se afirma capturar
- Chain-of-thought interno o razonamiento privado que un proveedor de IA no exponga en su API.
- Procesos cerrados sin interfaz estructurada ni exportación de logs.

### Privacidad y Redacción de Secretos
Antes de escribir a disco o transmitir a la red, un motor de redacción (`redact()`) sustituye tokens de autorización, claves privadas, cookies y patrones de API keys (`sk-*`, `rt_*`, `ghp_*`, Bearer tokens) por `[REDACTED_SECRET]`.

---

## 3. Componentes Implementados

### 3.1 `fme-trace`: CLI y Receptor Local
- Paquete Python instalable y ejecutable con la librería estándar.
- **Receptor OTLP / HTTP (`fme-trace serve`):** Escucha en `http://127.0.0.1:8787` y acepta trazas y métricas OpenTelemetry (`/v1/traces`, `/v1/logs`, `/v1/metrics`) y eventos JSON genéricos (`/events`).
- **Sincronizador (`fme-trace sync`):** Agrupa eventos de la cola local y los envía a RawTree mediante peticiones por lotes con tokens de deduplicación.
- **Inspector de cola (`fme-trace status`):** Muestra el número de eventos pendientes, edad del lote más antiguo y estado de conexión.

### 3.2 Cola Local Durable (Local-First)
- Cada evento se serializa en JSONL y se escribe en disco con `fsync` y bloqueos de proceso (`file_lock`).
- Si se activa `DEVFLIGHT_OFFLINE=1` o se pierde la conexión con RawTree, ningún evento se pierde.
- Al restaurar la conexión, el sincronizador reintenta los lotes pendientes manteniendo las identidades lógicas (`event_id`).

### 3.3 Tablas en RawTree
Los datos se almacenan en RawTree aprovechando su motor analítico sin esquema previo:

| Tabla | Propósito |
|---|---|
| `dev_events_raw` | Eventos semiestructurados de desarrollo (herramientas, prompts, respuestas, diffs). |
| `dev_artifacts_raw` | Fragmentos y metadatos de artefactos y archivos generados. |
| `dev_traces` | Spans de OpenTelemetry para correlación temporal. |
| `dev_logs` | Logs del sistema capturados mediante OTLP. |
| `dev_metrics` | Métricas numéricas de consumo y latencias. |

---

## 4. Explotación a Posteriori (Consultas SQL y Dashboards)

Dado que no se utiliza un modelo de IA para procesar la telemetría, el análisis se realiza mediante consultas SQL analíticas directas sobre RawTree:
- **Análisis de costes y tokens:** Agregación por desarrollador, modelo y sesión.
- **Detección de picos temporales:** Identificación de momentos de alta concurrencia o loops infinitos de subagentes.
- **Auditoría de herramientas:** Conteo de herramientas más invocadas y tasas de error.
- **Conexión a Dashboards (Side Challenge Crux):** Exportación de estas métricas hacia paneles de visualización para la toma de decisiones del equipo.
