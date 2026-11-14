# Evidencia y Estado de Aceptación Técnica

## Actualización: fase de ingesta verificada por API (14/11/2026)

- Base `datathon_mathops` creada en `datathon-upc-relus` / `relus-cluster` y app `opentelemetry` instalada con autorización.
- Token Bearer configurado en `.env`; autenticación HTTP comprobada. El UUID inicial era un ID de clave, no el token.
- 20 tests pasan, incluidos contexto de desarrollador/sesión, usage de proveedores y colector gzip/OTLP. Se conservan tests históricos del proyecto anterior como regresión.
- `scripts/telemetry_smoke.py`: ingesta y recuperación por HTTP API de eventos heterogéneos.
- `scripts/rawtree_verify.py`: recuperación exacta y restauración de artefacto desde RawTree con redacción de clave de prueba.
- Wrapper real ejecutado durante esta implementación: comandos, resultados y artefactos almacenados; subida automática completada, cero pendientes.
- OTLP local -> API nativa RawTree verificado con tres payloads de prueba etiquetados sintéticos.
- `scripts/verify_ingestion.py` verifica dos inserciones con el mismo token sin duplicado, recuperación exacta del desarrollo y tablas nativas. Informe: `telemetry-validation.json`.
- La comprobación inicial mediante MCP generó 18 filas sin `event_json`. Se conservan; para restauración exacta usar las filas con `event_json IS NOT NULL` y deduplicar por event_id. Los nuevos inserts HTTP incluyen siempre la copia serializada.

No se han invocado nuevas sesiones externas de Claude/Cursor ni se han medido costes de modelos. Los adaptadores se prueban con fixtures; las trazas de implementación corresponden a trabajo real de este asistente registrado mediante wrapper/SDK. No se implementa el dashboard ni el agente de análisis en esta fase.

Validación local realizada en Windows con Python 3.12. Paquete instalado en modo editable en `.venv`.

| Criterio | Evidencia | Estado |
|---|---|---|
| CLI instalable y SDK | `pip install -e .`, `fme-trace status`, tests de subprocesos | Verificado |
| Árbol de trazas, tools, RAG, artefactos | Reconstrucción por `trace_id` y cola durable | Verificado local |
| Redacción de secretos y datos heterogéneos | Pruebas de patrones (`sk-*`, Bearer, envs), gzip, SHA-256 | Verificado local |
| Caída/timeout incierto de red | Simulación de pérdida de ACK; reintento conserva lote y nuevos eventos | Verificado simulado |
| Concurrencia y segmento incompleto | Múltiples escritores simultáneos, secuencias únicas con `file_lock` | Verificado local |
| Ingestión HTTP y OpenTelemetry (OTLP JSON) | Endpoint `/events`, `/v1/traces`, `/v1/logs`, `/v1/metrics` en `:8787` | Verificado local |
| Resiliencia offline (`DEVFLIGHT_OFFLINE=1`) | Encolado append-only sin red; sincronización al reconectar | Verificado local |
| Desacople analítico (Sin IA interna) | Sistema libre de dependencias de modelos LLM para procesar eventos | Verificado por diseño |
| Conexión con RawTree | Cliente HTTP configurado con cabeceras de deduplicación y tokens Bearer | Verificado a nivel de contrato |

---

## Comandos de Verificación del Sistema

```powershell
# 1. Ejecutar el conjunto completo de tests unitarios (17 tests)
./.venv/Scripts/python.exe -m unittest discover -s tests -v

# 2. Generar eventos de prueba de agentes y subprocesos
./.venv/Scripts/python.exe scripts/demo.py

# 3. Comprobar el estado de la cola durable local
./.venv/Scripts/fme-trace.exe --home .devflight/demo status

# 4. Probar la ejecución de predict y eval en modo demo offline
./.venv/Scripts/python.exe predict.py --input data/demo.jsonl --output .devflight/predictions.csv --backend demo
./.venv/Scripts/python.exe eval.py --input data/demo.jsonl --predictions .devflight/predictions.csv --recipe demo --tokens 0 --recipe-config data/recipe.json
```

---

## Estado de la Conexión Externa a RawTree

Las credenciales del equipo están configuradas en `.env` (`RAWTREE_API_KEY` y `RAWTREE_READ_KEY` hacia `https://api.rawtree.com`).
Al conectar contra la API en la base `datathon_mathops`, la autenticación y formato de cabeceras es la estándar `Authorization: Bearer <token>` y `x-rawtree-database`. Cuando la base autorizada esté activa y la clave habilitada en RawTree, ejecutar `scripts/rawtree_verify.py` para validar la transferencia en vivo.
