# Verificación de la entrega

Fecha: 15 noviembre 2026. Windows, Python 3.13 del entorno local.

- Suite local final: 37 tests, 8,964 s. Incluye los 20 originales, cinco productores concurrentes, 100 eventos íntegros, redacción, recuperación de artefactos, cursor tras timeout ambiguo, manifiesto antiguo no contiguo, checkpoints interrumpidos, bloqueo de Host/Origin, clave de control vacía, límite de disco, parada autenticada y reinicio HTTP real.
- RawTree real: `scripts/rawtree_verify.py --home .devflight/final-live-probe` devolvió `verified=true`, 8 eventos. Trace ID: `ee405f1a588124acd011f52679023aed`. Se compararon sobres completos y se restauró el artefacto. No se invocó un modelo.
- MCP RawTree de solo lectura: `dev_traces` contiene 11.215 filas, 11.215 pares traceId/spanId únicos y 935 trazas. Cero spans con timestamp de inicio de los últimos 30 minutos en la consulta realizada. No se atribuye el histórico a una sesión.
- Frecuencias: `fs.get_metadata` 3.633; `fs.read_file` 2.663; `append_items` 808; `receiving` 593. Son nombres de spans, no una medición de coste o memoria.
- El perfil essential de Codex desactiva explícitamente trazas heredadas, probado mediante regresión. No se midió una sesión interactiva real con/sin OTLP; su sobrecarga y RAM de jornada completa no quedan certificadas.
- Integraciones: configuradores y recepción estándar probados localmente; no se abrieron sesiones reales de Claude, Gemini ni Qwen. Se requieren versiones compatibles y configuración inicial.
- Pitch: 8 diapositivas, PPTX editable con 8 notas y PDF de 8 páginas. Renderizado e inspección visual de todas las diapositivas; validadores de integridad y geometría sin incidencias. No se afirma haber abierto el archivo en Microsoft PowerPoint.
- Qualcomm: repo `jan-lozano-dev/datathon-2026` en a99c11b contiene solo README. Referencia oficial `mpous/datathon-UPC-maths-qualcomm-arduino-unoq` en f1ae321 usada solo para presentar requisitos. El código local `copilot/pipeline.py` y `eval.py` contiene implementación Teach/Reason y evaluación, sin artefactos del resultado ≈46 %. El 46 % documentado de cobertura textual no es accuracy.

Pendiente: validación interactiva de agentes, medición prolongada, retención automática sin pérdida de archivos históricos, AI Analyst autónomo y dashboard empresarial. Los documentos antiguos de visión no certifican funcionalidades presentes; README, PERFORMANCE y este archivo son la referencia operativa.
