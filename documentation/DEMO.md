# Demo: RawTree compartido y decisiones del reto principal

Esta guía describe un recorrido para ejecutar con datos y claves reales. No afirma que esta revisión ya haya superado las pruebas.

## Preparación

Arranca con `devflight.cmd start` (Windows) o `.venv/bin/python start_platform.py start` (Unix). Entra en [http://127.0.0.1:8788](http://127.0.0.1:8788) con la credencial local.

En Configuración confirma el nombre/base de RawTree y la cobertura de tablas. Revisa la entrega local. El botón de comprobación del analista consulta el catálogo de Helmcode; la investigación posterior comprueba la inferencia.

## Recorrido para el jurado

1. **Problema:** varios agentes y usuarios generan actividad dispersa durante el reto principal. Abre Inicio y Emisores para mostrar el agregado de la fuente compartida.
2. **Historia real:** elige «Todo el historial», localiza una sesión y revisa IDs, herramientas y errores. Explica cualquier emisor desconocido.
3. **RawTree como herramienta del agente:** pregunta en AI Analyst qué patrones de error aparecen y cómo verificarlos. Muestra los pasos de consulta elegidos por el modelo, la evidencia SQL y las incertidumbres.
4. **Acción:** guarda una vista de seguimiento. Enseña su verificación y abre la vista en Explorer. Un fallo de consulta debe quedar visible.
5. **Tukey y Qualcomm:** abre Experimentos con evaluaciones reales. Compara variantes solo cuando dataset/split/suite/hardware coincidan; usa idioma/tema/dificultad para justificar una decisión del proyecto principal.
6. **Trazabilidad:** enseña el estado de envío y el registro de la investigación. Distingue recepción local de confirmación remota.

No hace falta generar fixtures para esta historia. Si se usa la opción sintética de Configuración, sus datos deben identificarse como tales.

## Demo programática opcional

```cmd
.venv\Scripts\python.exe scripts/platform_demo.py --live --followup-view
```

Realiza una compilación observada por SDK, busca el ID exacto en RawTree y en la API, envía una investigación asíncrona con alcance compartido, espera su estado final y comprueba su auditoría. `--followup-view` añade la acción y su verificación. Tiene plazos acotados y requiere las claves configuradas.

`--scope organization` permite una demo limitada a una organización; no es el comportamiento global por defecto. `--hours 0` permite todo el histórico.

Sin `--live`, exige una investigación previa y devuelve el modo `verified-history-replay-no-new-inference`. No se debe presentar como una nueva inferencia. Los snapshots de Explorer también se etiquetan como históricos.

[Detalle técnico y recorrido de comprobación](SHARED_SOURCE_AND_ANALYST.md).
