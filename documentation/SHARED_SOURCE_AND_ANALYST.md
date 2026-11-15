# Entrega: fuente RawTree compartida, AI Analyst y sidequests

## Alcance de esta revisión

La implementación se centra en tres flujos conectados:

| Flujo | Resultado en el producto | Código principal |
| --- | --- | --- |
| Observabilidad global | Estadísticas de las tablas compatibles de una fuente, sin filtro implícito por usuario del navegador | `shared.py`, `analytics.py` |
| Investigación | Conversación con herramientas RawTree, progreso durable, evidencia y acción de seguimiento | `intelligence.py`, `investigation_jobs.py`, `Analyst.tsx` |
| Decisiones del reto principal | Evaluaciones y desgloses con información de comparabilidad | `Experiments.tsx`, `eval.py`, `analytics.py` |

**Las pruebas funcionales y las suites no se ejecutan en esta entrega por petición del usuario.** Las compilaciones de Python/TypeScript sirven para preparar el código y el bundle; no certifican conectividad, precisión de los datos ni comportamiento en navegador. No hay claves RawTree/Helmcode en el entorno de implementación para acreditar una ejecución real.

Preparación de entrega completada: TypeScript y Vite compilan el frontend, y Python compila los módulos modificados. No se ejecutaron suites ni comprobaciones funcionales. El JavaScript inicial es de 279,37 KB; las gráficas se cargan por separado y su chunk de 540,48 KB mantiene un aviso de tamaño de Vite.

Los informes anteriores de `VALIDATION.md` y `PERFORMANCE.md` son evidencia histórica de otra revisión.

## 1. Semántica de la fuente y migración

No hay que reemplazar la base local ni borrar la cola. Al arrancar, se crean de forma aditiva las tablas SQLite del journal y de concesiones de acceso. Se conservan identidades, eventos pendientes y vistas anteriores.

La fuente se identifica mediante endpoint y base de datos. La organización original obtiene acceso a esa fuente. Las organizaciones adicionales requieren una concesión explícita de su propietario. La clave de lectura debe tener acceso a las tablas necesarias.

`dev_all_events` es una **proyección SQL virtual**, no una copia materializada que requiera volver a ingerir el histórico. Combina:

- `dev_platform_events`: nuevos eventos normalizados.
- `dev_events_raw`: envelopes del SDK y evaluaciones anteriores.
- `dev_logs`, `dev_traces`, `dev_metrics`: tablas OTLP nativas.

La proyección comprueba las columnas disponibles antes de construir SQL. Una tabla ausente se muestra en cobertura; un problema de autenticación/conexión no se convierte en un resultado «sin eventos». Las filas sin tiempo interpretable no entran en ventanas temporales, pero pueden verse en «Todo el historial».

Los snapshots y vistas nuevas incluyen la fuente. Una vista guardada para otra fuente requiere recrearse con el alcance correcto. El historial antiguo del analista sin metadatos de fuente se etiqueta como histórico no verificado; no sirve de contexto activo ni habilita una acción nueva.

### Identidades

El emisor debe enviar un identificador explícito, como `origin_user_id` o un atributo OTLP admitido. `DEVFLIGHT_DEVELOPER_ID` permite atribuir eventos del SDK. Es una declaración del productor, no una identidad personal verificada.

Los IDs autenticados de ingesta se guardan por separado. Las estadísticas nunca inventan usuarios distintos ni asignan todo el tráfico de una clave compartida a su propietario.

### Métricas

Los tokens representan lo reportado por los productores. La caché es una columna separada y sus semánticas pueden diferir entre proveedores. Los logs de consumo por evento se distinguen de métricas acumulativas y totales de sesión. Las observaciones sin consumo no cuentan como peticiones del modelo.

Se deduplican IDs de origen explícitos en su contexto de emisor/sesión; los eventos sin una equivalencia demostrable permanecen separados. La retención de deduplicación de RawTree es una condición operativa externa.

## 2. Contrato del analista

Crear una investigación:

```http
POST /api/investigations
Content-Type: application/json
```

```json
{
  "question": "¿Qué agentes concentran los errores y qué evidencia hay?",
  "scope": {"source_scope": "workspace", "hours": 24},
  "request_id": "un-identificador-unico-del-cliente"
}
```

La respuesta es HTTP 202 con `id`, `conversation_id` y `status`. Consultar `GET /api/investigations/{id}` devuelve el progreso. Para continuar la conversación se envía su `conversation_id` y un nuevo `request_id`.

Un reintento de red reutiliza el mismo ID y cuerpo; reutilizarlo con una pregunta/alcance diferente devuelve error. El journal conserva el trabajo antes de la primera llamada al modelo. Tras una interrupción, el trabajo se marca interrumpido y no se reinfiere automáticamente.

La herramienta debe obtener evidencia actual antes de concluir. Puede estrechar filtros, pero no ampliar el alcance. El SQL completo se conserva para inspección; al modelo se le da un contexto acotado con resultados y referencias, para no gastar el presupuesto en SQL repetido.

`POST /api/investigations/{id}/cancel` evita nuevos pasos. Una llamada remota en curso puede consumir recursos hasta su timeout; la interfaz lo explica.

### Acción de seguimiento

`POST /api/investigations/{id}/followup-view` crea una vista privada con el alcance de la investigación y ejecuta una consulta para verificarla. La vista y el marcador de reintento se guardan juntos; repetir la acción no crea otra vista. Los eventos de creación y verificación se envían por el outbox.

Si falla la verificación, se conserva la vista y aparece como pendiente, con posibilidad de reintentar. No se presenta como verificada solo porque se haya creado localmente.

## 3. Datos para Tukey

La pestaña Experimentos utiliza eventos `eval.grade`. No necesita prompts, enunciados, respuestas de alumnos ni soluciones; consume metadatos y medidas agregadas.

| Campo | Interpretación |
| --- | --- |
| `recipe`, `variant` | Variante evaluada |
| `dataset` | Identidad/hash del conjunto |
| `split` | Partición de evaluación |
| `suite_version` | Versión del procedimiento de evaluación |
| `hardware` | Dispositivo/runtime real que produjo las predicciones |
| `accuracy`, `count` | Exactitud y número de casos |
| `seconds`, `tokens` | Medidas observadas de esa ejecución |
| `breakdown` | Exactitud/cantidad por idioma, tema y dificultad |

Para generar cohortes completas, `eval.py` admite flags opcionales de metadatos. El cálculo de puntuación existente conserva su comportamiento.

```cmd
.venv\Scripts\python.exe eval.py --input datos.jsonl --predictions predicciones.csv --recipe baseline --recipe-config receta.json --tokens 1234 --split validation --suite-version "m3kang-eval-v1" --hardware "identificador-del-hardware-real" --variant baseline-v1
```

Los nombres y 1.234 tokens del ejemplo deben sustituirse por los de la ejecución real. No se deben emitir valores de muestra para llenar el dashboard. El evento queda en la cola del SDK y requiere su sincronización/configuración de RawTree. Para enviarlo desde esa misma configuración, ejecuta `.venv\Scripts\python.exe -m devflight sync` (o el equivalente de Unix); si utilizas una ruta de cola propia, pasa `--home RUTA` antes de `sync`. La cola SDK legacy y el outbox enterprise son almacenes distintos.

La identidad de dataset se calcula con el hash del archivo. Las cohortes comparables requieren dataset, split, suite y hardware completos e iguales. Si un histórico no los tiene, la aplicación muestra sus resultados con esa limitación. `seconds` es la suma de duración reportada en predicciones; no demuestra latencia por interacción ni consumo energético del Arduino.

## 4. Recorrido manual propuesto

Este recorrido queda para el usuario; no es un informe de pruebas ejecutadas.

1. Configurar las tres claves y arrancar. Revisar fuente, base y tablas en Configuración. Comprobar el modelo con el botón explícito.
2. Enviar eventos reales de dos emisores distintos a la misma fuente. Ver sus filas en Explorer y su agregado en Inicio/Emisores, sin cambiar el usuario de login.
3. Comparar el periodo seleccionado con «Todo el historial». Comprobar las mismas condiciones en Inicio, sesiones, Explorer y una pregunta al analista.
4. Revisar consumo con un evento de petición y una muestra acumulativa OTLP. Confirmar que no se suman como dos peticiones.
5. Consultar al analista: «Identifica los patrones de error de esta fuente, cita la evidencia y propón una comprobación». Ver progreso real, consultas y consumo. Continuar con «¿Qué cambia si miro ese agente?».
6. Guardar una vista de seguimiento y abrirla en Explorer. Revisar que el resultado sea verificado o que aparezca el error pendiente.
7. Emitir dos evaluaciones reales con el mismo dataset/split/suite/hardware y variantes distintas. Revisar exactitud, cantidad y desgloses en Experimentos.
8. Cortar temporalmente la conexión: comprobar pendientes y error, restaurar y revisar el ID remoto. Un ACK local no equivale a una confirmación remota.
9. Si se usan organizaciones adicionales, comprobar el comportamiento antes y después de conceder acceso a la fuente. Las conversaciones deben seguir siendo privadas.

### Comandos disponibles

```cmd
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe scripts/platform_demo.py --live --followup-view
```

La demo exige datos/conectividad reales. Sin `--live`, reutiliza una investigación anterior y la etiqueta; no finge una inferencia nueva. Las regresiones nuevas cubren formatos de telemetría, IDs, persistencia, scopes, presupuesto y trabajos asíncronos; están entregadas para que el usuario las ejecute.
