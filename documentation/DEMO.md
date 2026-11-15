# Demo del producto integrado

## Inicio

`devflight.cmd start` inicia el backend y reutiliza o inicia un único colector. Abrir `http://127.0.0.1:8788` e iniciar sesión con la credencial personal del archivo privado `.devflight/platform/admin.token`.

## Flujo para el jurado

1. Mostrar Overview y filtrar la sesión `b07066fb-8003-4f30-b235-ad393e2125fa` si se usa el entorno de esta implementación. No atribuir esos eventos SDK a una exportación completa de Codex.
2. Ejecutar `.venv\Scripts\python.exe scripts/platform_demo.py --live`: compila realmente el código, registra el resultado, verifica el ID exacto en RawTree y en la API del dashboard e inicia una investigación Helmcode acotada.
3. Abrir Sessions & Traces y seleccionar la sesión. Revisar eventos, IDs, duración y estado; las identidades de proveedor/modelo no emitidas permanecen desconocidas.
4. Abrir AI Analyst y revisar la investigación nueva: herramientas elegidas, SQL autorizado, evidencia y conclusión. El registro queda en SQLite y en RawTree. No hay acciones automáticas sobre otros procesos.
5. Abrir Data Explorer: escoger campos o agrupación, guardar una vista privada y exportar hasta 100 filas. La asignación de históricos requiere una acción explícita del propietario local para una traza exacta.

La demostración principal no fabrica errores ni actividad de un proveedor: analiza el trabajo de desarrollo capturado. Si no existen fallos, el analista debe indicar esa limitación. La opción de Settings para generar fixtures es explícitamente sintética y se marca en los datos y en Overview; no se necesita para el flujo real verificado.

## Alternativa de conexión limitada

`.venv\Scripts\python.exe scripts/platform_demo.py` reutiliza una investigación auditada y muestra `verified-history-replay-no-new-inference`. No ejecuta Helmcode ni debe presentarse como una nueva investigación. Para un corte de RawTree, una vista previamente consultada y guardada puede abrirse en `Verified snapshot mode` con exactamente sus mismos campos y filtros. Es evidencia histórica etiquetada, no una consulta en directo. El backend local debe seguir activo.

Los presupuestos de Helmcode se configuran privadamente. Se seleccionó qwen3.6 incluido en el catálogo del plan, reasoning desactivado y salidas cortas. No publicar claves ni tokens de sesión durante la presentación.

Las presentaciones existentes no se regeneran ni forman parte de este commit.
