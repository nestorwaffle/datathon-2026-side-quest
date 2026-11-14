# Rendimiento y alcance de validación

## Hallazgos

La cola anterior releía y ordenaba todos los eventos al insertar cada evento para calcular `sequence`, con trabajo acumulado cuadrático. Ahora recupera el máximo al abrir una instancia y guarda el siguiente número bajo bloqueo; la escritura local conserva `fsync`. La subida se hace en el hilo del colector, fuera del manejador HTTP. Se aceptan hasta 32 solicitudes simultáneas; ante saturación se responde `503` y `Retry-After: 1`, para que el exportador reintente. La cola local sigue siendo durable y sin límite de descarte.

Los sobres OTLP permanecen en la cola local para recuperación y deduplicación. Remotamente se envían solo a la tabla OTLP nativa correspondiente, evitando la segunda inserción en `dev_events_raw`. Los eventos no OTLP y artefactos conservan su ruta anterior. No se aplica muestreo, porque podría eliminar errores, uso o relaciones padre-hijo. RawTree puede descomponer un sobre OTLP en múltiples filas; el número de sobres no equivale al de spans ni a bytes físicos de almacenamiento. Los campos opcionales nulos conservan su semántica en la cola y RawTree puede omitir sus rutas dinámicas.

## Mediciones

Entorno: Windows, Python del entorno `.venv`, 15 noviembre 2026. Prueba sintética local de 200 eventos `tool.result`, sin red ni RawTree: después, 1,656 s de pared, 0,859 s de CPU, 131.582 bytes JSONL, 200 eventos útiles, 200 pendientes y cero pérdida observada. Línea base verificable: los 20 tests preexistentes pasaron en 2,841 s. No se capturó una medición numérica de 200 eventos antes del cambio; por ello no se declara una aceleración porcentual. La mejora de complejidad se verifica por el código y la regresión de concurrencia.

Los 20 tests existentes y las pruebas añadidas cubren cinco clientes HTTP concurrentes, unicidad de secuencias, persistencia de 100 eventos y una sola ruta remota OTLP mediante un cliente simulado. La prueba remota de RawTree, sesiones reales de Codex con y sin telemetría, CPU/RAM y bytes de red de agentes reales quedan pendientes; no se generan filas de prueba en la cuenta remota. El resultado sintético no mide la latencia interactiva de Codex.

## Operación

Configurar el exportador oficial de cada agente una vez y reiniciar sus sesiones. Codex: [referencia de configuración](https://developers.openai.com/docs/config-file/config-reference). Claude Code: [variables OTEL admitidas](https://code.claude.com/docs/en/monitoring-usage). El servicio recibe varias sesiones simultáneas, pero la atribución de proveedor, modelo, desarrollador y sesión depende de los atributos emitidos por el agente; los valores ausentes no se inventan.
