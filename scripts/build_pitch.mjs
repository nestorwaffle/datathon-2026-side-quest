// Reproducible editable pitch. Requires the authoring-only @oai/artifact-tool package.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const modulePath = process.env.ARTIFACT_TOOL_MODULE;
const {Presentation, PresentationFile} = await import(modulePath ? pathToFileURL(modulePath).href : '@oai/artifact-tool');
const out = path.resolve('deliverables');
const preview = path.resolve('tmp/pitch-preview');
await fs.mkdir(out,{recursive:true}); await fs.mkdir(preview,{recursive:true});
const p = Presentation.create({slideSize:{width:1280,height:720}});
const C={bg:'#101519',ink:'#F2F4F1',muted:'#A9B5B7',lime:'#C3F482',blue:'#8CC9E8',line:'#364349'};
function text(s,t,x,y,w,h,size=28,color=C.ink,bold=false){const a=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});a.text=t;a.text.style={fontFamily:'Arial',fontSize:size,color,bold};return a;}
function base(n,label,title){const s=p.slides.add();s.background.fill=C.bg;text(s,label.toUpperCase(),70,44,1100,28,16,C.lime,true);text(s,title,70,114,1130,140,52,C.ink,true);text(s,'FME DATATHON 2026     /     RELUS',70,660,950,24,14,C.muted);text(s,String(n).padStart(2,'0'),1150,654,60,32,20,C.muted);return s;}
function diagram(s,labels,y=320){const gap=28,w=(1140-gap*(labels.length-1))/labels.length;labels.forEach((label,i)=>{const x=70+i*(w+gap);s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:140},fill:'#19252B',line:{fill:C.line,width:1}});text(s,label,x+18,y+25,w-36,100,25,C.ink,true);if(i<labels.length-1)text(s,'›',x+w-2,y+42,32,55,28,C.lime);});}
let s=base(1,'Qualcomm main challenge + RawTree side challenge','Aprender matemáticas.\nEntender a nuestros agentes.');
text(s,'IA matemática offline  /  DevFlight',73,350,1110,70,36,C.blue);
text(s,'Etna · Guillem · Nestor',73,490,1000,44,27,C.muted);
s.speakerNotes.text='[20 s] Hemos trabajado en dos proyectos distintos. El reto principal es acercar la ayuda matemática al alumno mediante una IA local. El side challenge, DevFlight, observa a los agentes de programación que usamos para desarrollar. Comparten equipo y contexto, pero el dispositivo educativo no depende de RawTree. Fuentes: documentación/QUALCOMM_CONTEXT.md; PDF oficial RawTree.';
s=base(2,'Main challenge · problema','Ayudar a razonar,\ntambién sin conexión');
text(s,'El alumno necesita un siguiente paso\nque pueda comprender y comprobar.',72,300,1080,120,38);
text(s,'Teach: guiar con pistas breves.\nReason: elegir una respuesta A–E y medir el acierto.',72,485,1080,100,29,C.muted);
s.speakerNotes.text='[22 s] El problema educativo es ayudar a dar el siguiente paso sin convertir la herramienta en una máquina de copiar respuestas. El objetivo del main challenge es ejecutar el copiloto en Arduino UNO Q y aprovechar M3Kang. El código local incluye Teach y Reason: pistas acotadas para aprender y respuestas A a E para evaluar. La experiencia final en hardware sigue pendiente de verificación independiente. Fuente: copilot/pipeline.py y documentación/QUALCOMM_MAIN_CHALLENGE.md.';
s=base(3,'Main challenge · solución','Una arquitectura pensada\npara ejecutar en local');
diagram(s,['Problema\nM3Kang','Python\nTeach / Reason','Modelo local\nllama.cpp','Respuesta\nPista o A–E']);
text(s,'Destino: Arduino UNO Q  ·  Sin API de nube en el camino offline',72,520,1110,65,28,C.blue);
text(s,'Diagrama de arquitectura; despliegue final en placa no verificado.',72,594,1110,35,19,C.muted);
s.speakerNotes.text='[24 s] El camino offline llama solo a endpoints locales, con proxies desactivados. Python prepara el problema y puede recuperar ejemplos cortos antes de consultar llama.cpp. El repositorio conserva además un backend remoto de desarrollo; esa variante no es la demostración offline. No hemos verificado la placa en esta sesión y lo distinguimos del código disponible. Fuente: copilot/pipeline.py, local_post, Index y solve.';
s=base(4,'Main challenge · datos y modelo','M3Kang como banco\nde aprendizaje y evaluación');
text(s,'Qwen3.5 0.8B Q8_0',72,300,1120,70,43,C.blue,true);
text(s,'Modelo del kit oficial y las notas del equipo; no inspeccionado en placa.',72,379,1120,42,22,C.muted);
text(s,'Recuperación opcional de ejemplos · Pistas verificadas\nEvaluación A–E · Desglose por idioma, tema y dificultad',72,485,1110,110,28);
s.speakerNotes.text='[25 s] El kit oficial y las notas del equipo señalan Qwen3.5 0.8B cuantizado Q8_0 y embeddings bge-small-en-v1.5. El código local incorpora recuperación, evita usar el mismo problema como ejemplo y limita las pistas a opciones revisadas. El evaluador compara predicciones con etiquetas y genera desgloses. No se encontró un fichero de predicciones del equipo que permita confirmar el resultado actual. Fuentes: https://github.com/mpous/datathon-UPC-maths-qualcomm-arduino-unoq en f1ae321, README secciones 4 y 9, usado solo para la presentación; documentación/QUALCOMM_CONTEXT.md; eval.py; copilot/pipeline.py.';
s=base(5,'Main challenge · evidencia','Resultados con una frontera clara');
text(s,'≈46 %',72,280,650,120,94,C.lime,true);
text(s,'Accuracy comunicada por el equipo\nPROVISIONAL · sin evaluación reproducible localizada',74,425,1110,96,29);
text(s,'No equivale al 46 % de problemas de solo texto documentado en M3Kang.\nPendiente: predicciones, split, versión del modelo y prueba en UNO Q.',74,555,1110,66,21,C.muted);
s.speakerNotes.text='[22 s] El equipo comunica aproximadamente un 46 por ciento de accuracy, pero todavía no disponemos de sus predicciones ni del protocolo de evaluación para confirmarlo. Hay además un 46 por ciento en la documentación que describe la cobertura de problemas de solo texto; no lo usamos como resultado del modelo. Por rigor, la cifra sigue provisional. El siguiente paso es adjuntar split, versión, predicciones y tiempos medidos en UNO Q. Fuente: comunicación del usuario y documentación/QUALCOMM_CONTEXT.md. Repositorio de referencia a99c11b contiene solo README.';
s=base(6,'RawTree side challenge · DevFlight','Los agentes programan.\nSu comportamiento debe ser observable.');
text(s,'Sesiones · Herramientas · Errores\nModelos · Tokens disponibles · Duraciones',73,333,1110,118,35,C.blue);
text(s,'Un colector residente para clientes compatibles.\nPerfil ligero: logs útiles y trazas internas desactivadas.',73,510,1110,95,28,C.muted);
s.speakerNotes.text='[22 s] Mientras construíamos el proyecto principal apareció otro problema: múltiples agentes y terminales producen actividad difícil de comparar. DevFlight recibe OTLP JSON y eventos estructurados, redacta secretos, escribe una cola durable y sincroniza fuera de la interacción del agente. El perfil essential de Codex desactiva explícitamente las trazas heredadas. La configuración depende de las capacidades oficiales de cada cliente; no prometemos captura universal. Fuentes: devflight/collector.py, core.py e integrations.py.';
s=base(7,'RawTree side challenge · datos verificados','Una ruta durable hasta RawTree');
diagram(s,['Agentes\nOTLP / SDK','Colector\nRedacción','Cola durable\nReintentos','RawTree\nJSON + OTLP'],280);
text(s,'8 eventos: ida y vuelta real + restauración íntegra de artefacto',72,467,1135,54,30,C.lime,true);
text(s,'11.215 spans históricos · 935 trazas · identificadores únicos\nLas operaciones internas explican volumen; no se asume duplicación.',72,548,1120,75,23,C.muted);
s.speakerNotes.text='[27 s] Hemos comprobado de verdad ocho eventos pequeños de prueba y la recuperación exacta de un artefacto. RawTree devuelve 11.215 spans distintos repartidos en 935 trazas históricas; las operaciones más frecuentes son metadatos y lectura de ficheros. No inferimos una sesión única ni duplicados. OTLP se inserta solo en tablas nativas; los eventos estructurados conservan su tabla JSON. Un agente puede explorar este historial por el MCP oficial; el AI Analyst autónomo de producto sigue pendiente. Fuentes: consulta MCP RawTree a datathon_mathops y scripts/rawtree_verify.py, trace ee405f1a588124acd011f52679023aed; documentación/VALIDATION.md.';
s=base(8,'FME Datathon 2026 · cierre','Aprender con IA.\nConstruir con evidencia.');
text(s,'Qualcomm',73,339,490,55,37,C.blue,true);text(s,'Ayuda matemática local\nTeach + Reason',73,416,490,95,30);
text(s,'DevFlight + RawTree',660,339,550,55,37,C.lime,true);text(s,'Telemetría durable y consultable\nBase verificada para investigar agentes',660,416,550,95,30);
text(s,'Siguiente hito: evaluación en placa y analista autónomo con evidencia SQL.',73,582,1120,50,23,C.muted);
s.speakerNotes.text='[18 s] El valor del main challenge es acercar una ayuda matemática local al estudiante. El del side challenge es hacer observable el software que construimos con agentes. RawTree permite conservar datos heterogéneos y consultarlos sin diseñar previamente cada esquema. Entregamos una base de telemetría probada y somos explícitos sobre lo pendiente: validar el modelo en placa y completar el agente autónomo de investigación. Gracias. Duración total prevista: aproximadamente tres minutos.';
await (await PresentationFile.exportPptx(p)).save(path.join(out,'Datathon_2026_Final_Pitch.pptx'));
try { await fs.rename(path.join(out,'Datathon_2026_Final_Pitch.pptx.inspect.ndjson'),path.join(preview,'export-inspection.ndjson')); } catch(error) { if(error.code!=='ENOENT') throw error; }
for(let i=0;i<p.slides.items.length;i++){
 const blob=await p.slides.items[i].export({format:'png',scale:1});
 await fs.writeFile(path.join(preview,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));
}
console.log(JSON.stringify({pptx:path.join(out,'Datathon_2026_Final_Pitch.pptx'),slides:p.slides.items.length,preview}));
