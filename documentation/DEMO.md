# Guion de Demostración de 3 Minutos (Pitch para el Jurado)

## Historia y Narrativa

> *«Para construir nuestro copiloto de matemáticas en Arduino UNO Q, nuestro equipo ha utilizado de forma intensiva agentes y asistentes de programación con IA (Claude Code, Codex, Cursor y scripts). Pero en cualquier equipo u organización surge un reto crítico: los agentes generan un torrente masivo de eventos sin orden, consumen miles de tokens y nadie sabe con certeza dónde se concentran los costes o cuándo ocurren picos anómalos.*
> 
> *Para resolver esto, creamos una plataforma complementaria e independiente: un colector universal basado en OpenTelemetry y una cola durable local que ingiere indiscriminadamente toda la telemetría de desarrollo y la almacena en RawTree, dejándola lista para auditoría y análisis SQL a posteriori.»*

---

## Estructura del Pitch (3 Minutos)

### Minuto 0:00 – 0:45 · El problema y la arquitectura
1. **Presentar el escenario:**
   - Mostrar el flujo de trabajo de programación asistida por IA del reto Qualcomm.
   - Explicar la necesidad de centralizar telemetría heterogénea (llamadas a herramientas, tokens, errores, sesiones) sin depender de un esquema rígido.
2. **La arquitectura:**
   - Agentes de desarrollo (Claude Code / Codex / CLI) $\rightarrow$ OpenTelemetry OTLP JSON / HTTP $\rightarrow$ Colector Local DevFlight $\rightarrow$ RawTree (Tinybird OLAP).
   - Enfatizar que **no usamos modelos de IA adicionales para analizar**: el valor es la captura pura, la resiliencia y el almacenamiento para análisis posterior.

### Minuto 0:45 – 1:45 · Captura heterogénea, privacidad y resiliencia offline
1. **Recepción local de telemetría:**
   ```powershell
   ./.venv/Scripts/fme-trace.exe --home .devflight/telemetry collect --port 8787
   ```
2. **Demostrar redacción de secretos:**
   - Enviar un evento con una clave o credencial en el payload.
   - Mostrar cómo el colector redacta automáticamente el token (`[REDACTED_SECRET]`) antes de persistir nada a disco o enviarlo a RawTree.
3. **Resiliencia ante caídas de red:**
   ```powershell
   # Simular corte de red
   $env:DEVFLIGHT_OFFLINE = '1'
   ./.venv/Scripts/fme-trace.exe --home .devflight/demo sync
   ./.venv/Scripts/fme-trace.exe --home .devflight/demo status
   # La cola conserva todos los eventos pendientes con manifiesto transaccional

   # Restaurar red y sincronizar
   $env:DEVFLIGHT_OFFLINE = '0'
   ./.venv/Scripts/fme-trace.exe --home .devflight/demo sync
   ```

### Minuto 1:45 – 2:30 · Almacenamiento en RawTree y consultas SQL (a posteriori)
1. **Datos en RawTree:**
   - Mostrar cómo los eventos se han volcado en las tablas de RawTree (`dev_events_raw`, `dev_traces`).
   - Resaltar la ventaja de RawTree: ingiere datos JSON con tipos variables sin requerir migraciones de base de datos.
2. **Consultas SQL demostrativas:**
   - **Picos de uso:** Consultar la distribución horaria de eventos para detectar momentos de saturación.
   - **Gasto de tokens:** Ver qué desarrolladores o sesiones consumieron la mayor parte del presupuesto de tokens.
   - **Uso de herramientas:** Identificar qué comandos de bash, lecturas de archivos o subagentes fallaron con mayor frecuencia.

### Minuto 2:30 – 3:00 · Conclusiones e impacto
1. **Independencia limpia:**
   - El proyecto de Qualcomm corre offline en la placa Arduino sin sobrecostes ni telemetría obligatoria en producción.
   - El proyecto de RawTree acumula la memoria histórica completa del desarrollo con total fidelidad.
2. **Listo para dashboards (Crux / BI):**
   - Explicar que estos datos almacenados en RawTree pueden conectarse directamente a un dashboard (Power BI, Streamlit o Tableau) para monitorización continua en tiempo real.
