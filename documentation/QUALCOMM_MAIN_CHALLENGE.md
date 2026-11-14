# Datathon FME 2026 - Qualcomm main challenge

Fuente: repositorio oficial [`mpous/datathon-UPC-maths-qualcomm-arduino-unoq`](https://github.com/mpous/datathon-UPC-maths-qualcomm-arduino-unoq).

## Reto

Disenar y construir un copilot de matematicas que se ejecute enteramente en Arduino UNO Q y use el dataset M3Kang de forma innovadora para ayudar a estudiantes a razonar matematicamente.

La solucion debe cumplir al menos una de estas modalidades:

### Teach

Convertir la capacidad del modelo en una experiencia que despierte curiosidad y guie al estudiante sin darle la respuesta. Ejemplos: pistas, practica adaptativa, analisis de errores, interaccion fisica o colaboracion.

### Reason

Al recibir un problema estilo Kangaroo, elegir la respuesta correcta. La organizacion lo medira sobre un conjunto oculto.

## Material disponible

- **M3Kang**: dataset multilingue de miles de problemas de la competicion Kangaroo, con idiomas y dificultades variados.
- **Arduino UNO Q, 4 GB**: CPU Arm Qualcomm QRB2210 para modelos de lenguaje, embeddings y recuperacion local; microcontrolador en tiempo real para LEDs, botones, sensores y camaras.
- Ningun dato tiene que abandonar el dispositivo durante el uso normal.

El setup oficial incluye `llama.cpp`, Qwen3.5 0.8B como modelo de lenguaje, `bge-small-en-v1.5` para embeddings, `predict.py`, `eval.py` y herramientas de RAG. En la implementacion se debe usar la version de modelo realmente provisionada en la placa, no asumir una variante distinta por nombre.

## Restricciones de rendimiento

La placa es capaz pero lenta para generar: aproximadamente 11 tokens/s de lectura y 5 tokens/s de escritura segun el enunciado. Los prompts largos cuestan tiempo; embeddings y retrieval cuestan una fraccion de segundo.

La arquitectura debe por tanto:

- Enrutar la intencion antes de llamar al LLM.
- Recuperar contexto corto y relevante.
- Mantener respuestas de ayuda breves.
- Medir exactitud, tiempo de respuesta y uso de herramientas.
- Operar offline despues de la preparacion inicial.

## Entregables

- Repositorio GitHub abierto y documentado.
- Proyecto en Arduino Project Hub con arquitectura, experiencia, reproduccion y analisis de errores por tema, idioma y dificultad.
- Demo en directo y pitch de tres minutos.

## Decision adoptada para este proyecto

Se implementaran ambos modos sobre el mismo nucleo:

- **Study / Teach** como experiencia de usuario principal: pista socratica, deteccion de error y siguiente paso minimo; nunca muestra la solucion ni la opcion correcta antes de que el alumno razone.
- **Challenge / Reason** como banco objetivo: contesta A-E y permite medir el rendimiento con M3Kang.

DevFlight mide el desarrollo de ambos modos. No forma parte del flujo online del alumno ni es necesario para que el Arduino funcione offline.
