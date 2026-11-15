# Checkpoint del producto

Implementado: recuperación y seguridad del colector; FastAPI + React/TypeScript/Tailwind/ECharts; identidades SQLite WAL, organizaciones/equipos/proyectos/roles y claves personales; outbox durable a RawTree; consultas agregadas autorizadas, explorador, vistas, CSV y snapshots; AI Analyst Helmcode real con herramientas y auditoría; captura explícita del desarrollo por SDK.

Verificación: 57 tests pasan; build frontend y npm audit aprobados; diez rutas reales devuelven 200; demo live e investigación remota por IDs concretos aprobadas. VALIDATION.md contiene evidencia y límites.

Ejecución observada: b07066fb-8003-4f30-b235-ad393e2125fa. Investigación live: 8df677f3-0222-4265-b42b-60965a5559cc. Cobertura parcial por SDK, sin prompts/código ni reconstrucción retroactiva.

Límites: host de navegador no disponible; sobrecarga interactiva de Codex no medida; proveedores ausentes sin sesión real certificada; colector legacy existente conservado, ingesta autenticada disponible en 8788; despliegue local, sin certificación para exposición pública.

Presentaciones y Qualcomm intactos. El commit de este checkpoint contiene el producto integrado. La publicación se verifica contra main en GitHub; las claves y el estado de captura permanecen fuera de Git.
