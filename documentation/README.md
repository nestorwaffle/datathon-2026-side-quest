# Documentación del Datathon FME 2026

Esta carpeta contiene el contexto, arquitectura y especificación técnica de la plataforma de **Observabilidad de Agentes de IA con RawTree y OpenTelemetry**, diseñada como un complemento independiente al proyecto principal de Qualcomm.

## Índice de documentos

**Implementación de la fase 1:** [TELEMETRY_QUICKSTART.md](TELEMETRY_QUICKSTART.md) contiene los comandos actuales para capturar y sincronizar. La analítica/dashboard queda fuera de esta fase.

| Documento | Descripción |
|---|---|
| [OBSERVABILIDAD_AGENTES_RAWTREE.md](OBSERVABILIDAD_AGENTES_RAWTREE.md) | **Documento maestro**: Visión, arquitectura y caso de uso de la plataforma de telemetría para Claude Code, Codex y otros agentes hacia RawTree. |
| [RETO_QUALCOMM_CONTEXTO.md](RETO_QUALCOMM_CONTEXTO.md) | Contexto oficial del reto principal de Qualcomm (Arduino UNO Q, dataset M3Kang, reparto del equipo). |
| [RAWTREE_SIDE_CHALLENGE.md](RAWTREE_SIDE_CHALLENGE.md) | Enunciado y criterios del side challenge de RawTree. |
| [DEVFLIGHT_IMPLEMENTATION_PLAN.md](DEVFLIGHT_IMPLEMENTATION_PLAN.md) | Especificación técnica del recolector durable, ingesta OTLP y conector RawTree. |
| [ADAPTERS.md](ADAPTERS.md) | Especificación de adaptadores de telemetría (OpenTelemetry OTLP JSON, Claude Code, Codex, MCP). |
| [DEMO.md](DEMO.md) | Guion de la demostración de 3 minutos para el jurado. |
| [VALIDATION.md](VALIDATION.md) | Registro de pruebas locales, cobertura y estado de validación. |

---

## Relación entre proyectos y arquitectura

1. **Proyecto Qualcomm (Reto Principal):**
   - Un tutor matemático que corre enteramente offline en **Arduino UNO Q** con el dataset M3Kang (modos Teach y Reason).
   - Desarrollado por el equipo (Etna, Guillem, Nestor) utilizando herramientas y agentes de programación con IA (Claude Code, Codex, Cursor, etc.).

2. **Proyecto de Observabilidad con RawTree (Este repositorio):**
   - **Complemento totalmente independiente:** No interfiere en la ejecución offline del Arduino.
   - **Objetivo:** Capturar y almacenar indiscriminadamente toda la telemetría generada por las IAs y agentes que el equipo utiliza durante el desarrollo del proyecto Qualcomm.
   - **Ingesta universal:** Recibe eventos heterogéneos (tokens, herramientas, sesiones, subagentes, latencias, errores) mediante **OpenTelemetry (OTLP)** y la API/MCP de RawTree.
   - **Almacenamiento en RawTree:** Aprovecha que RawTree (Tinybird) es una base de datos analítica OLAP sin esquema previo para acumular todo el historial crudo sin fricción.
   - **Sin agentes de IA internos:** Este proyecto **no** incluye un agente LLM que analice los datos. El valor radica en la captura resiliente (local-first) y el almacenamiento centralizado para que a posteriori cualquier analista, dashboard o consulta SQL pueda auditar costes, picos y patrones de uso.
