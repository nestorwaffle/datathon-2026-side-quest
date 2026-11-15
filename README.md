# DevFlight — RawTree compartido y AI Analyst

Plataforma local de observabilidad para DATATHON. El dashboard consulta **todos los emisores, agentes y sesiones de la fuente RawTree autorizada**, incluidos los históricos de las tablas compatibles. El inicio de sesión controla el acceso; no convierte la sesión del navegador en el universo de datos.

## Presentación y demo final

- [Presentación HTML](deliverables/DevFlight_Pitch.html): ocho diapositivas con transiciones; se avanza con las flechas, espacio o un clic. Descarga también `deliverables/pitch-assets/` para abrirla sin conexión.
- [PowerPoint editable](deliverables/DevFlight_Pitch.pptx): mismo relato, preparado para pasar diapositivas.
- [Vídeo final](deliverables/DEMO_FINAL.mp4): demostración grabada de DevFlight, RawTree, AI Analyst y la acción de seguimiento.

Las cifras de la presentación son una instantánea del 15 de noviembre de 2026. La investigación de AI Analyst que aparece en pantalla es un análisis anterior, guardado con evidencia. El proyecto Qualcomm solo se menciona en el cierre como fuente complementaria de actividad.

RawTree conserva los eventos analíticos. FastAPI aplica permisos y construye SQL. React muestra las estadísticas y un analista conversacional conectado a Helmcode. SQLite guarda identidades, trabajos del analista, vistas privadas y una cola de envío durable.

## Qué incluye

- **Dashboard global:** actividad, errores, emisores, sesiones, consumo reportado y estado de la fuente. Los filtros son explícitos; «Todo el historial» elimina el límite temporal.
- **Datos existentes:** proyección común de `dev_platform_events`, `dev_events_raw`, `dev_logs`, `dev_traces` y `dev_metrics`. No es necesario volver a enviar los históricos compatibles.
- **Ingesta:** OTLP/HTTP JSON, eventos planos y envelopes de los SDK; identidad del emisor separada de la identidad autenticada.
- **AI Analyst:** conversación con contexto acotado, selección real de herramientas, progreso persistente, cancelación, historial privado, evidencia SQL y consumo informado por el proveedor.
- **Acción verificable:** desde una investigación se puede guardar una vista privada de seguimiento; la aplicación ejecuta una consulta de verificación y registra la acción.
- **Experimentos:** evaluaciones `eval.grade` del reto Qualcomm, exactitud, duración, tokens y desgloses. Las comparaciones completas requieren el mismo dataset, split, versión de suite y hardware.
- **Explorer:** tabla virtual `dev_all_events`, tablas individuales, filtros, agrupaciones, paginación, CSV y vistas privadas.
- **Entrega visible:** pendientes, antigüedad, último intento, última confirmación y error. Aceptación local, confirmación de escritura y visibilidad en una consulta son estados diferentes.

La aplicación se sirve en español. La presentación de DevFlight y el vídeo final están en `deliverables/`.

## Instalar y arrancar

Python 3.11 o posterior. El frontend compilado está incluido; Node se necesita para modificarlo.

### Windows CMD

```cmd
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install ".[platform]"
copy .env.example .env
```

Rellena en tu entorno privado:

```dotenv
RAWTREE_API_KEY=
RAWTREE_READ_KEY=
RAWTREE_BASE_URL=https://api.rawtree.com
RAWTREE_DATABASE=datathon_mathops
DEVFLIGHT_SOURCE_NAME=RawTree compartido
HELMCODE_API_KEY=
HELMCODE_BASE_URL=https://api.helmcode.com/v1
HELMCODE_MODEL=qwen3.6
```

```cmd
devflight.cmd start
```

Abre [http://127.0.0.1:8788](http://127.0.0.1:8788). El primer arranque genera la credencial de administración en `.devflight/platform/admin.token`; introdúcela en el formulario. No compartas ese archivo. `devflight.cmd status`, `restart` y `stop` administran los servicios.

### Linux o macOS

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ".[platform]"
cp .env.example .env
# Rellenar .env antes de continuar.
.venv/bin/python start_platform.py start
```

La aplicación escucha en loopback. Las claves de RawTree y Helmcode permanecen en el backend. Si se cambia la configuración de la fuente, hay que reiniciar la plataforma.

## Qué significa «global»

La fuente se identifica por **endpoint y base de datos**, no por el texto de una API key. Rotar una clave manteniendo su fuente no cambia el ámbito. Solo aparecen las tablas que la clave de lectura puede consultar.

La organización inicial de la instalación tiene acceso a la fuente compartida. Sus miembros pueden ver las estadísticas globales. Otras organizaciones conservan su aislamiento hasta que el propietario de la instalación les concede acceso desde Configuración. Un administrador de otra organización no puede concedérselo a sí mismo.

`org_id`, `user_id` y `ingest_user_id` representan la autenticación de ingesta. `origin_user_id`, `origin_user_name` y `origin_id_source` describen la procedencia declarada del evento. **Una API key compartida no identifica a todos sus usuarios.** Los eventos sin identificador de origen aparecen como desconocidos.

Los filtros de periodo, sesión, proveedor, modelo, emisor, agente, proyecto, equipo y ejecución se aplican en el servidor. Las preguntas al analista conservan una copia de su alcance. Cambiar un filtro del dashboard no modifica una investigación ya iniciada.

Las conversaciones y las vistas guardadas son privadas por usuario y organización, aunque su evidencia pueda abarcar toda la fuente.

## Captura y normalización

En Configuración crea las credenciales de ingesta. Los exportadores pueden enviar con `Authorization: Bearer <credencial>` a:

- `POST http://127.0.0.1:8788/api/events`: evento plano o envelope SDK.
- `POST http://127.0.0.1:8788/v1/logs`: logs OTLP JSON.
- `POST http://127.0.0.1:8788/v1/traces`: trazas OTLP JSON.
- `POST http://127.0.0.1:8788/v1/metrics`: métricas OTLP JSON.

El colector dedicado 8787, cuando arranca en modo enterprise, utiliza las mismas credenciales y almacenamiento. Elige un destino por exportador.

La normalización contempla atributos reales de Codex y Claude, números enviados como strings, errores de herramientas, costes y caché. Conserva gauge, sum, histogram, summary y exponentialHistogram con su temporalidad y distribución. Un tipo métrico desconocido devuelve error y no se confirma como si se hubiera recibido correctamente.

Se priorizan IDs explícitos del productor para reconocer reintentos. OTLP sin ID recibe una identidad derivada del registro y su contexto. La consulta compartida elimina duplicados con IDs de origen coincidentes dentro del mismo emisor/sesión. No deduce que dos observaciones diferentes son la misma llamada solo por parecerse.

El SDK JavaScript mantiene ID y timestamp entre reintentos. Su retry HTTP no sustituye una cola persistente del cliente; dispone de `prepare()` y `send()` para aplicaciones que necesiten guardar el evento antes de enviar.

Las integraciones oficiales de agentes necesitan configuración y reinicio de sus sesiones. Encontrar un endpoint configurado no acredita entrega real. No se captura retroactivamente actividad ni razonamiento privado.

## Métricas con límites explícitos

Las filas son **eventos**, no necesariamente peticiones al modelo. Los contadores de sesión, las muestras acumulativas y los tokens en spans no se suman como consumo por petición junto a sus logs de uso.

Los tokens de entrada y salida son los reportados por cada proveedor. La semántica de caché puede variar; los contadores de caché se mantienen separados y no se añaden otra vez al total de entrada. Un valor ausente permanece `null`; no se convierte en coste cero ni se inventa una tarifa.

La cobertura muestra qué tablas se han podido consultar. El histórico disponible depende de los datos que ya existan en RawTree y de sus permisos. Los campos desconocidos o sin timestamp admitido tienen limitaciones visibles; «Todo el historial» permite explorar sin excluirlos por fecha.

## AI Analyst y sidequest RawTree

El analista utiliza `HELMCODE_MODEL`, con `qwen3.6` por defecto. No se promete que una cuenta concreta tenga acceso al modelo: **Comprobar conexión** consulta el catálogo del proveedor; una investigación real permite comprobar además la inferencia y las herramientas.

El flujo es:

1. Guardar pregunta, alcance, conversación y `request_id` antes de inferir.
2. Recuperar contexto acotado de la conversación.
3. Permitir que el modelo elija consultas estructuradas sobre RawTree.
4. Guardar SQL, resultados, errores, tiempos y consumo de cada paso.
5. Solicitar una conclusión con hallazgos, incertidumbre, acción propuesta y verificación.
6. Si el usuario pulsa la acción de seguimiento, guardar una vista, consultarla y auditar el resultado.

`POST /api/investigations` devuelve **202** con el ID del trabajo. La interfaz consulta su progreso. Repetir el mismo `request_id` con el mismo cuerpo recupera el mismo trabajo. Una interrupción del proceso conserva checkpoints y no repite automáticamente una inferencia que podría haber sido facturada.

Los límites por defecto son 3 iteraciones, 4 consultas, 512 tokens de salida por llamada, 6.000 tokens de presupuesto y 60 segundos; hay dos trabajos concurrentes y una cola acotada. La admisión del contexto utiliza una estimación y el consumo real se conserva cuando el proveedor lo informa. El plazo se propaga a las consultas RawTree. Cancelar evita nuevos pasos; una llamada que ya esté en curso puede terminar y consumir tokens.

La IA no recibe credenciales, prompts de los productores ni SQL arbitrario ejecutable. Las consultas se construyen en backend y no pueden ampliar el alcance elegido. El consumo interno del analista se etiqueta y se excluye de los disparadores de anomalías de desarrollo.

## Sidequest Tukey y reto principal

La pestaña **Experimentos** conecta el dashboard con las evaluaciones reales del proyecto Qualcomm. Lee los eventos `eval.grade` existentes del SDK y los nuevos eventos normalizados que incluyan `evaluation`.

Muestra exactitud, cantidad de casos, duración observada y tokens, además de desgloses por idioma, tema y dificultad cuando se hayan emitido. Expone dataset, split, receta/variante, versión de suite y hardware. Si faltan metadatos de cohorte, no afirma que dos ejecuciones sean comparables. La duración de evaluación no se presenta como latencia interactiva del dispositivo.

Ejemplos de decisiones útiles: localizar categorías con menor exactitud, contrastar variantes sobre el mismo conjunto y detectar ejecuciones incompletas. Los datos necesarios, el flujo de demo y los límites están en [la guía de entrega](documentation/SHARED_SOURCE_AND_ANALYST.md).

## Durabilidad y operación

SQLite WAL y el outbox durable permiten confirmar recepción local antes de una escritura remota. El uploader conserva los IDs y los lotes entre reintentos. Los errores de inicialización, autenticación o conexión quedan visibles. `DEVFLIGHT_OFFLINE=1` detiene la subida.

La capacidad local está limitada por `DEVFLIGHT_PLATFORM_MAX_BYTES` (512 MiB por defecto). Al saturarse, se rechazan nuevas aceptaciones con error reintentable. El archivado opcional conserva los payloads confirmados en gzip; no elimina pendientes. La deduplicación remota también depende de la configuración y retención de RawTree; no se promete entrega exactamente una vez para siempre.

Los snapshots de Explorer están vinculados al usuario, fuente, alcance y consulta exacta. Se etiquetan como históricos y vuelven a comprobar permisos al leerlos.

## Compilación y pruebas a cargo del usuario

Esta entrega incluye código de regresión y el frontend compilado. **Las pruebas funcionales, las suites de tests y las comprobaciones con cuentas reales se dejan al usuario por petición expresa.** Los resultados históricos de documentos anteriores no validan esta revisión.

```cmd
.venv\Scripts\python.exe -m unittest discover -s tests -q
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

Para la demo real, una vez configuradas las claves:

```cmd
.venv\Scripts\python.exe scripts/platform_demo.py --live
```

Este comando genera una operación de compilación observada, comprueba su ID remoto y lanza una investigación real. Sin `--live`, exige una investigación previa y etiqueta su reutilización como histórica.

Consulta [la guía de entrega y comprobación manual](documentation/SHARED_SOURCE_AND_ANALYST.md), [la demo](documentation/DEMO.md) y [el caso de uso RawTree](documentation/RAWTREE_SIDE_CHALLENGE.md).
