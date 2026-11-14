# Reto Qualcomm — contexto para el equipo y los agentes

Datathon FME 2026 (UPC). Entrega: **domingo 15/11 a las 12:00**. Demo y pitch de 3 min: domingo a las 14:00. Premios: domingo a las 17:30.
Repo oficial: https://github.com/mpous/datathon-UPC-maths-qualcomm-arduino-unoq (trabajamos en un fork).

## El reto
> Diseñar un copiloto de mates que funcione **entero en la Arduino UNO Q, offline**, y que use el dataset **M3Kang** de forma innovadora para ayudar a los estudiantes a razonar.

**La nota se reparte 50 % Reason y 50 % Teach** (confirmado por el equipo el sábado; hay que hacer los dos).

| Parte | Peso | Cómo se evalúa |
|---|---|---|
| **Reason** | 50 % | Objetivo: acierto de `predict.py` en un **test oculto** de problemas tipo Canguro. Solo cuenta cuántos acierta. |
| **Teach** | 50 % | Jurado: una experiencia que guíe al alumno **sin darle la respuesta** (pistas, práctica adaptativa, análisis de errores, interacción física…). "Los usos más originales de M3Kang puntuarán más". |

Entregables: repo público en GitHub y post en **Arduino Project Hub** (arquitectura, cómo replicarlo, **análisis de errores por tema, idioma y dificultad**), y demo en directo en la placa con un pitch de 3 min.

Preguntas de autoevaluación del README (13.4): ¿usa M3Kang de una forma que otros no usarán? ¿Guía sin dar la respuesta? ¿Usa la placa (matriz LED, offline)? ¿Se mide con un número antes y después? ¿Cabe en 60 s por paso y 4 GB? ¿Se puede enseñar en 3 min?

## Hardware: Arduino UNO Q (4 GB)
- Linux (Debian) en un Qualcomm QRB2210 (4× Cortex-A53), más un microcontrolador STM32 (sketches de Arduino en C++) para la matriz LED, botones y sensores.
- Unos **3,6 GB de RAM usable**. Con los dos servidores (LLM y embeddings) cargados quedan unos 2,5 GB libres.
- **No hay `pip`**: el código que corre en la placa solo puede usar la librería estándar de Python.
- SLM: **Qwen3.5 0.8B Q8_0** en `llama-server`, puerto 8081. Embeddings: **bge-small-en-v1.5** (384 dimensiones), puerto 8082. Ambos corren con llama.cpp en un commit fijo (`config.env`).
- Velocidad: **lee unos 11 tokens/s** (un prompt de 400 tokens son unos 36 s) y **escribe unos 6 tokens/s**. Un embedding cuesta una fracción de segundo. La visión (mmproj) tarda 28–38 s por imagen y no se recomienda (el stand de Qualcomm desaconseja un VLM).
- **Límite: 60 s por problema.** Si se pasa, la respuesta es `D`. Temperatura 0 obligatoria.

## Datos: M3Kang
- Problemas del concurso Canguro (2007–2024), multilingües. El kit usa el split `high_quality`, shard 0: **1.747 problemas en inglés** (más los mismos en catalán).
- Campos tras `prepare_m3kang.py`: `id` (p. ej. `lvl-0_2015_5`), `language`, `level` (0 = los más pequeños, 7 = los mayores), `year`, `text_only`, `text` (enunciado **sin** opciones), `options` (A–E, leídas de la imagen con OCR, o `{}`) y `label`.
- **Las opciones solo están en la imagen**, y el OCR (RapidOCR, en el portátil) las lee en el **62 %** de los problemas. En el resto son dibujos o el OCR falla.
- **Solo texto: 46 %** (811 de 1.747 en inglés). Por nivel: 0 → 20 %, 1 → 26 %, 2 → 32 %, 3 → 49 %, 4 → 46 %, 5 → 57 %, 6 → 53 %, 7 → 56 %. En los problemas con figura **el texto no describe la figura**.
- No hay campo de tema: hay que añadirlo (palabras clave o clasificación).
- Licencia solo para investigación: **no subir `data/*.jsonl` ni las imágenes al repo**.

## Puntos de partida (README, 40 problemas)
| Método | Acierto |
|---|---|
| Azar | 20 % |
| Siempre `D` | 25 % |
| Baseline (una letra con gramática A–E) | **22,5 %** (9/40). Sesgo: 21 veces D y 14 veces A |
| Una línea de razonamiento + letra | 17,5 % (y 3 veces más lento) |
| RAG con 2 ejemplos | Sin mejora clara, unos 30 s por problema |

Referencia del paper de M3Kang: Qwen2.5-3B (con imagen) saca un 30 % en inglés, y Gemma-1B queda por debajo del azar.
**Techo realista para nosotros: 31–36 %.** Buen resultado: 30–33 %.

## Plan Reason (50 %): `copilot/pipeline.py` → `solve()`
1. **Logprobs de A–E + calibración del sesgo** (prior por letra estimado en train y validado en val). Es la idea de PriDe y de la contextual calibration.
2. **Detectar si el problema es de solo texto o con figura**: `text_only` o palabras clave ("figure", "picture", "shown").
3. **Con figura o sin opciones**: no gastar el SLM; responder la mejor letra por defecto según el nivel (aprendida en train).
4. **Solvers con reglas en Python** para aritmética, porcentajes y conteo simple; buscar la opción que coincide con el resultado.
5. **Usar la versión en inglés** del mismo `id` si el test viene en otro idioma.
6. **Regresión logística** sobre las señales (logprobs, entropía, nivel, idioma, opciones leídas, solver): se entrena en el portátil y los pesos se copian al código.
7. Mejorar el OCR de las opciones (Guillem), para subir del 62 %.

Bucle: un cambio, `python3 eval.py --limit 200 --name <cambio>`, anotarlo en `ablations.csv`, commit con el número y, después, comprobar los tiempos en la placa.

## Plan Teach (50 %): reutilizar las piezas de Reason
Recomendación: **entrenador adaptativo + escalera de pistas**, con web servida por la placa y la matriz LED.
- **Entrenador adaptativo**: el alumno responde A–E en la web y el LED muestra ✓ o ✗ y su nivel. Si acierta, el siguiente es un problema parecido (embeddings) de un nivel más; si falla, uno del mismo tema y un nivel menos. El perfil se guarda en SQLite en la placa. No usa el LLM, así que es instantáneo.
- **Escalera de pistas**, cuando falla: (1) un problema parecido más fácil, ya resuelto; (2) el tema o el método, a partir del clasificador de temas de Reason; (3) una pista de una frase del SLM, que **Python comprueba que no contiene el valor de la respuesta**; (4) la solución, solo si la pide.
- **Métricas para el pitch**: % de pistas que revelan la respuesta (comprobado con código en todo val), tiempo por paso, y alumnos simulados (¿el sistema converge al nivel correcto?).
- Herramienta: el skill `unoq-hardware-ui` (App Lab: web y matriz LED).
- Ideas alternativas del README: debate en clase (votación más un SLM que hace de abogado del diablo), puente multilingüe catalán↔inglés, adaptación para dislexia y discalculia.

## Reparto
- **Etna**: Reason (`copilot/`, `predict.py`, experimentos en el portátil con `llama-server` local).
- **Guillem**: la placa (montaje, servicios, probar cada versión en ella), mejora del OCR y del campo de tema, y la UI de Teach (web y LED) con su agente.
- **Nestor**: side challenge de RawTree, con un dashboard de errores por tema, idioma, nivel y versión (sirve también para el análisis de errores de Qualcomm y para el side de visualización), el pitch y la publicación en Project Hub.

## Reglas para los agentes
- En la placa: solo librería estándar. `predict.py` devuelve una letra A–E por problema, con temperatura 0, en menos de 60 s.
- No cambiar la interfaz de `predict.py` ni de `eval.py`.
- No subir datos, imágenes ni claves.
- Un cambio cada vez, medido y con commit.
- Los tiempos medidos en el portátil no valen: se comprueban en la placa.

## Preguntas abiertas para la organización
- ¿El test oculto llega como `val.jsonl` (texto y opciones ya extraídas, `text_only`) o con imagen? ¿En qué idiomas? ¿Cuántos problemas tiene?
- ¿Cómo se puntúa Teach exactamente (criterios del jurado)?
- ¿Nos quedamos la placa?
