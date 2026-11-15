# Demo de fase 1 y presentación

Duración del pitch: aproximadamente 3 minutos. El guion y las fuentes están en las notas de las ocho diapositivas de `deliverables/Datathon_2026_Final_Pitch.pptx`.

## Demostración técnica breve

1. Mostrar `start_devflight.py status`: colector, cola local y contadores remotos, con sus fuentes diferenciadas.
2. Ejecutar `.venv\Scripts\python.exe scripts/rawtree_verify.py --home .devflight/demo-verification`. Necesita las claves privadas configuradas en `.env`. Produce ocho eventos pequeños de prueba y recupera su contenido exacto y un artefacto. No llama a modelos. Repetir crea un nuevo conjunto pequeño, no un benchmark de carga.
3. Mostrar `verified=true`, el identificador de traza y la consulta concreta. Los eventos están identificados por el agente `live-probe`; no son actividad de un usuario real.
4. Consultar RawTree mediante SQL/MCP: contar spans y pares de IDs únicos; agrupar por operación. La evidencia de esta entrega figura en VALIDATION.md. No presentar el histórico como una sola sesión.

El AI Analyst autónomo integrado y el dashboard empresarial no están incluidos. Un agente externo puede usar el MCP oficial de RawTree para decidir consultas, pero eso no prueba un ciclo autónomo de producto. No se simula dicho ciclo con respuestas fijas.

Para Qualcomm, solo mostrar una ejecución en placa y accuracy si el equipo aporta esas evidencias. El pitch marca ≈46 % como provisional. El dataset de investigación, imágenes y modelos no se distribuyen en esta entrega.
