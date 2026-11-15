# Rendimiento y alcance de validación

## Hallazgos

La cola anterior releía y ordenaba todos los eventos al insertar cada evento para calcular `sequence`, con trabajo acumulado cuadrático. Ahora recupera el máximo al abrir una instancia y guarda el siguiente número bajo bloqueo; la escritura local conserva `fsync`. La subida se hace en el hilo del colector, fuera del manejador HTTP. Se aceptan hasta 32 solicitudes simultáneas; ante saturación se responde `503` y `Retry-After: 1`, para que el exportador reintente. La cola local sigue siendo durable y sin límite de descarte.

Los sobres OTLP permanecen en la cola local para recuperación y deduplicación. Remotamente se envían solo a la tabla OTLP nativa correspondiente, evitando la segunda inserción en `dev_events_raw`. Los eventos no OTLP y artefactos conservan su ruta anterior. No se aplica muestreo, porque podría eliminar errores, uso o relaciones padre-hijo. RawTree puede descomponer un sobre OTLP en múltiples filas; el número de sobres no equivale al de spans ni a bytes físicos de almacenamiento. Los campos opcionales nulos conservan su semántica en la cola y RawTree puede omitir sus rutas dinámicas.

## Mediciones

Entorno: Windows, Python del entorno `.venv`, 15 noviembre 2026. Prueba sintética local de 200 eventos `tool.result`, sin red ni RawTree: después, 1,656 s de pared, 0,859 s de CPU, 131.582 bytes JSONL, 200 eventos útiles, 200 pendientes y cero pérdida observada. Línea base verificable: los 20 tests preexistentes pasaron en 2,841 s. No se capturó una medición numérica de 200 eventos antes del cambio; por ello no se declara una aceleración porcentual. La mejora de complejidad se verifica por el código y la regresión de concurrencia.

Medición posterior del mismo caso sintético: 1,465 s de pared, 0,688 s de CPU y 131.582 bytes JSONL para 200 eventos. Son ejecuciones individuales con ruido del sistema, no una afirmación porcentual. La comprobación de cola dañada solo lee el último byte en el caso normal. El estado local usa el cursor durable y no recorre todos los eventos. La sincronización toma una instantánea por ciclo y conserva un manifiesto de lote para reintentos.

Los 20 tests existentes y las pruebas añadidas cubren cinco clientes HTTP concurrentes, unicidad de secuencias, persistencia de 100 eventos y una sola ruta remota OTLP mediante un cliente simulado. La prueba remota de RawTree, sesiones reales de Codex con y sin telemetría, CPU/RAM y bytes de red de agentes reales quedan pendientes; no se generan filas de prueba en la cuenta remota. El resultado sintético no mide la latencia interactiva de Codex.

## Operación

Configurar el exportador oficial de cada agente una vez y reiniciar sus sesiones. Codex: [referencia de configuración](https://developers.openai.com/docs/config-file/config-reference). Claude Code: [variables OTEL admitidas](https://code.claude.com/docs/en/monitoring-usage). El servicio recibe varias sesiones simultáneas, pero la atribución de proveedor, modelo, desarrollador y sesión depende de los atributos emitidos por el agente; los valores ausentes no se inventan.

## Cierre de fase 1

35 pruebas locales aprobadas (9,212 s). El ciclo real aislado de HTTP comprueba arranque, ingesta, parada autenticada y reinicio sin pérdida. La verificación remota ha confirmado ocho eventos y restauración exacta de un artefacto en RawTree; no es una prueba de rendimiento de modelos.

La sincronización ya no reconstruye la lista pendiente por cada lote: usa un mapa ordenado y un cursor en la instantánea del ciclo. El historial todavía se lee una vez al sincronizar y reconciliar al iniciar. El estado confirmado utiliza un cursor y solo mantiene identificadores dispersos heredados hasta cerrar sus huecos. Se registra el tiempo acumulado de ingesta y los reintentos.

DEVFLIGHT_MAX_QUEUE_BYTES permite aplicar backpressure sin borrar históricos: al alcanzar el límite de JSONL/segmentos se devuelve 503. El valor 0 conserva la política anterior sin límite. No incluye logs ni manifiestos y no representa retención automática. Se conserva fsync antes de confirmar captura para no perder eventos confirmados.

MCP RawTree: 11.215 spans históricos y 11.215 pares de IDs distintos, 935 traceId; cero recientes en la ventana consultada de 30 minutos. Las dos operaciones más frecuentes son fs.get_metadata (3.633) y fs.read_file (2.663). Esto muestra ruido interno, no duplicación demostrada. Essential desactiva explícitamente el exportador de trazas en Codex; no se descartan errores de lotes aceptados mediante sampling.

## Comparación controlada del cierre

`scripts/benchmark_queue.py`, 200 eventos sintéticos de la misma forma, un solo productor, sin red, 20 lecturas de status. Baseline: core.py del commit e6bc91a; después: core.py de esta entrega. Ejecuciones individuales en el mismo entorno, no un estudio estadístico.

| Métrica | Baseline | Después |
|---|---:|---:|
| Escritura de 200 eventos | 1,4480 s | 1,4626 s |
| CPU total | 0,9375 s | 0,8438 s |
| Status medio | 0,4000 ms | 0,3082 ms |
| JSONL | 135.582 bytes | 135.582 bytes |
| Eventos pendientes íntegros | 200 | 200 |
| Transferencia de red | 0 | 0 |

No se observa una aceleración de escritura en esta pequeña muestra; el control de recuperación adicional tiene coste. No se ha eliminado fsync para obtener una mejora artificial. El cambio principal corrige pérdida tras checkpoint/manifiesto interrumpido y reduce recorridos por lote. Sin una prueba interactiva de Codex no se certifica sobrecarga imperceptible.
