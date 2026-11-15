> **Documento histórico:** los resultados y las afirmaciones de este archivo corresponden a la revisión anterior. No validan los cambios de fuente compartida/analista asíncrono. El estado y las comprobaciones pendientes de esta entrega están en [SHARED_SOURCE_AND_ANALYST.md](SHARED_SOURCE_AND_ANALYST.md).

# Verificación actual — DevFlight 0.2

Fecha: 15 noviembre 2026. Windows, Python 3.13. La validación anterior de captura (37 tests y 8 eventos RawTree) se conserva como antecedente; los resultados siguientes son de la implementación integrada actual.

## Pruebas ejecutadas

- 57 tests Python aprobados en 11,692 s. Incluyen captura concurrente, recuperación y shutdown HTTP, redacción, manifiesto legacy no contiguo, checkpoint interrumpido, error transitorio de reemplazo de archivo en Windows, outbox SQLite con cinco productores y reapertura, timeout ambiguo con nuevos eventos, retención sin borrar pendientes, autenticación, roles, revocación, aislamiento de organización y caché/exportaciones/snapshots, cambio de permisos sobre sesiones existentes y límites de herramientas del analista.
- Frontend React/TypeScript: `tsc --noEmit` y Vite production build aprobados. ECharts actualizado específicamente a 6.1.0 tras un aviso de XSS. `npm audit` final: cero vulnerabilidades reportadas.
- Endpoints reales con sesión autenticada: `/`, overview, agents, sessions, people, usage, settings, investigations, explorer/tables y anomalies devolvieron HTTP 200 con RawTree real.
- Data Explorer: consulta real de la ejecución actual aprobada; recuperación del mismo alcance mediante `Verified RawTree snapshot` aprobada. No se descargaron datasets completos.
- Esquemas reales inspeccionados con `LIMIT 0`: dev_logs 78 campos, dev_traces 131, dev_metrics 9, dev_events_raw 117 y dev_artifacts_raw 32. Sus campos de tiempo difieren. El histórico permanece sin asignación organizativa automática.

## Telemetría real de esta implementación

Ejecución SDK: `b07066fb-8003-4f30-b235-ad393e2125fa`. Es observación explícita parcial: comandos de regresión/build y metadatos de archivos seleccionados. No incluye prompts, código, pensamiento privado ni reconstrucción de actividad anterior.

El primer comando de regresión falló por un PermissionError de Windows al reemplazar sequence.json. Su resultado se capturó como fallo real de comando; se corrigió el reemplazo transitorio y las regresiones finales pasan. No se atribuye la cobertura SDK a una exportación completa de Codex.

Demo live final:

- Evento `983af6e4f6b8875172f134517e7384068f83ef09c956e4049ca5828fa45bc78d`: compilación Python realmente ejecutada, exactamente una fila por su ID en RawTree y el mismo ID visible en la API de sesiones del dashboard.
- Investigación `8df677f3-0222-4265-b42b-60965a5559cc`: llamada por HTTP al backend, Helmcode qwen3.6, selección de dos herramientas reales, consultas RawTree y conclusión con evidencia. Auditoría remota por ID: una fila.
- Uso reportado por Helmcode de esa investigación: 2.556 tokens de entrada, 329 de salida, 2.885 en total. Dos iteraciones; no se guardó reasoning_content. No se inventa coste monetario.
- Repetición sin inferencia nueva: evento `cf247ab7728ec37e228dab3c69b266d755f6e739fb8f8044510e642069dd01ad`, una fila exacta, con el modo explícito `verified-history-replay-no-new-inference`. No se presenta como otra investigación autónoma.

El productor SDK determinista anterior verificó además un cálculo real 385 por HTTP y RawTree. No fue una inferencia Codex. Los tests de permisos y fallos usan clientes simulados explícitos; las dos investigaciones Helmcode verificadas usaron red y herramientas reales.

## Recursos y límites

Backend FastAPI: 55,94 MiB de memoria residente; 0,0 s de CPU adicional durante una ventana orientativa de 2 s en reposo. No equivale a una prueba de jornada completa ni a una comparación interactiva de Codex. El bundle principal final es aproximadamente 811 kB sin comprimir; el build emite un aviso de tamaño, no un error.

No se pudo realizar revisión visual: el host de navegador de CUA no estaba disponible. Compilación, rutas y datos fueron comprobados; no se declara aprobada la apariencia en navegador.

El colector preexistente de este equipo responde como versión legacy sin API de parada autenticada. Se preservó; la ingesta multiempresa funciona en el API autenticado 8788. No se mató un proceso por PID no verificado. Nuevas instancias del colector incluyen parada autenticada y están cubiertas por pruebas. Claude/Gemini/Qwen no están instalados; sus sesiones reales no se certifican. Codex está instalado, pero no se midió su latencia interactiva con/sin OTLP.

Se conservaron las presentaciones HTML/PPTX/PDF y el proyecto Qualcomm sin cambios.
