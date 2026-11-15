// Editable DevFlight pitch. Run with ARTIFACT_TOOL_MODULE pointing at the bundled artifact-tool module.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const workspaceDir=path.resolve('.');
const skillDir=process.env.PRESENTATIONS_SKILL_DIR;
const artifactModule=process.env.ARTIFACT_TOOL_MODULE;
const runtimePython=process.env.RUNTIME_PYTHON;
if(!skillDir||!artifactModule||!runtimePython) throw new Error('Set PRESENTATIONS_SKILL_DIR, ARTIFACT_TOOL_MODULE and RUNTIME_PYTHON.');
const {Presentation,PresentationFile}=await import(pathToFileURL(artifactModule).href);
const {finalizePresentation}=await import(pathToFileURL(path.join(skillDir,'container_tools/artifact_tool_utils.mjs')).href);
const buildDir=path.join(workspaceDir,'tmp','pitch-build');
const assetDir=path.join(workspaceDir,'deliverables','pitch-assets');
const finalPath=path.join(workspaceDir,'deliverables','DevFlight_Pitch.pptx');
const candidatePath=path.join(buildDir,'DevFlight_Pitch.candidate.pptx');
await fs.mkdir(buildDir,{recursive:true});
await fs.mkdir(path.dirname(finalPath),{recursive:true});

const p=Presentation.create({slideSize:{width:1280,height:720}});
const C={bg:'#09130D',ink:'#F3F7F0',muted:'#A5B5A7',lime:'#C7F36D',soft:'#D8E4D5',line:'#315038'};
function txt(s,t,x,y,w,h,size=28,color=C.ink,bold=false,font='Arial'){
  const a=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  a.text=t;a.text.style={fontFamily:font,fontSize:size,color,bold,wrap:true};return a;
}
function slide(n,kicker,title,notes){
  const s=p.slides.add();s.background.fill=C.bg;
  txt(s,'◈ DevFlight',70,32,420,36,24,C.ink,true);
  txt(s,'FME DATATHON 2026',960,38,255,24,14,C.muted,true);
  txt(s,kicker.toUpperCase(),70,86,1080,26,16,C.lime,true);
  if(title)txt(s,title,70,126,1140,148,54,C.ink,true);
  txt(s,String(n).padStart(2,'0')+' / 08',1125,668,90,25,16,C.muted);
  s.speakerNotes.text=notes+' Fuente visual: DEMO_FINAL.mp4, captura del 15 de noviembre de 2026.';
  return s;
}
async function photo(s,name,x,y,w,h,alt){
  const bytes=await fs.readFile(path.join(assetDir,name));
  const blob=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
  s.images.add({blob,contentType:'image/jpeg',alt,fit:'cover',position:{left:x,top:y,width:w,height:h},geometry:'rect'});
}

let s=slide(1,'Observabilidad de agentes con RawTree','',
  'DevFlight reúne actividad de agentes en la fuente RawTree compartida. Presentamos una cadena real: evento, consulta, análisis y seguimiento.');
txt(s,'Tus agentes.\nUna visión completa.',70,205,595,235,76,C.ink,true);
txt(s,'Actividad dispersa convertida en una investigación que podemos comprobar.',72,480,580,110,32,C.soft);
await photo(s,'overview_focus.jpg',715,215,500,355,'Vista general real de DevFlight');
txt(s,'Capturas de la demo final · 15 nov 2026',70,656,800,25,16,C.muted);

s=slide(2,'El problema','Un fallo deja pistas en demasiados sitios',
  'Las sesiones, las herramientas y los errores de distintos agentes quedan dispersos. DevFlight permite seguir una ejecución con sus eventos y procedencia.');
txt(s,'Sesiones, herramientas y errores quedan repartidos entre agentes. Seguir una ejecución exige reconstruir su historia.',70,305,460,180,30,C.soft);
txt(s,'¿Qué ocurrió y en qué sesión?',70,555,470,60,30,C.lime,true);
await photo(s,'sessions_focus.jpg',570,315,640,310,'Sesiones y trazas reales en DevFlight');

s=slide(3,'Cómo funciona','Una cadena que se puede auditar',
  'La actividad se emite desde los agentes. RawTree conserva el historial. El dashboard y el analista consultan la misma fuente. La recomendación puede convertirse en una vista guardada y verificada.');
const steps=[
  ['01','Actividad','Los agentes emiten eventos de sesiones y herramientas.'],
  ['02','RawTree','Conserva el historial de la fuente compartida.'],
  ['03','Consulta','SQL y AI Analyst examinan los mismos datos.'],
  ['04','Acción','Una vista guardada permite seguir el hallazgo.'],
];
steps.forEach(([num,head,body],i)=>{
  const x=70+i*295;
  txt(s,num,x,324,240,38,24,C.lime,true);
  txt(s,head,x,390,265,60,38,C.ink,true);
  txt(s,body,x,472,260,120,24,C.soft);
});
txt(s,'De cada afirmación podemos volver al evento.',70,624,1050,38,29,C.lime,true);

s=slide(4,'Datos presentes en la fuente','Una vista de todos los emisores autorizados',
  'Instantánea de la demo: 11.672 eventos visibles, 116 sesiones y 12 errores reportados. El propio dashboard señala 33 eventos sintéticos dentro del alcance. Son cifras de la captura, no un contador en vivo de esta presentación.');
txt(s,'11.672',70,320,380,80,68,C.lime,true);txt(s,'eventos visibles',70,404,350,32,23,C.soft);
txt(s,'116 sesiones',70,470,420,42,34,C.ink,true);txt(s,'12 errores reportados',70,527,420,42,29,C.ink,true);
await photo(s,'overview_focus.jpg',515,310,695,318,'Dashboard con métricas reales de RawTree');
txt(s,'Instantánea del 15 nov 2026 · Incluye 33 eventos marcados como sintéticos.',70,646,1040,32,17,C.muted);

s=slide(5,'Fuente verificable','La telemetría responde a SQL',
  'Esta consulta de lectura se ejecutó en RawTree sobre la tabla real dev_platform_events y devolvió resultados. El SQL mostrado aquí resume exactamente la consulta de la captura.');
txt(s,'SELECT event_type, status,\n       agent, tool,\n       count() AS events\nFROM datathon_mathops.\n     dev_platform_events\nGROUP BY event_type,\n         status, agent, tool\nORDER BY events DESC\nLIMIT 15',70,290,495,340,22,C.soft,false,'Consolas');
await photo(s,'rawtree_focus.jpg',595,300,615,330,'SQL ejecutado en RawTree con resultados');
txt(s,'Consulta de lectura real. La captura muestra filas devueltas.',70,646,1060,28,17,C.muted);

s=slide(6,'Investigación guardada','AI Analyst consulta y deja evidencia',
  'La investigación anterior, guardada, ejecutó dos consultas en RawTree. En el momento de esa investigación había 12 errores entre 11.669 eventos. El analista recomendó examinar las sesiones afectadas y explicitó límites; la recomendación no prueba por sí misma una causa raíz.');
txt(s,'El analista eligió dos consultas, examinó errores y actividad, y propuso verificar las sesiones afectadas.',70,310,490,156,29,C.soft);
txt(s,'12 errores',70,506,425,64,48,C.lime,true);
txt(s,'entre 11.669 eventos',70,568,450,45,27,C.ink);
await photo(s,'analyst_focus.jpg',590,310,620,300,'Investigación anterior de AI Analyst con evidencia');
txt(s,'Análisis anterior, guardado. La recomendación no prueba una causa raíz.',70,648,1090,28,17,C.muted);

s=slide(7,'Acción de seguimiento','De la respuesta a una vista verificada',
  'La interfaz conserva SQL y resultados de la investigación. La vista de seguimiento se guardó y consultó. Explorer muestra los eventos save_followup_view y verify_followup_view con estado ok.');
await photo(s,'evidence_focus.jpg',70,312,545,248,'SQL y resultado que sustentan el análisis');
await photo(s,'explorer_focus.jpg',645,312,565,248,'Eventos de seguimiento visibles en Explorer');
txt(s,'SQL y resultado de la investigación',70,575,535,30,21,C.soft);
txt(s,'Vista guardada y eventos de verificación',645,575,565,30,21,C.soft);
txt(s,'save_followup_view  ·  verify_followup_view  ·  estado ok',70,628,1140,42,28,C.lime,true);

s=slide(8,'DevFlight hoy','',
  'La demo final de 77 segundos muestra actividad real, consulta SQL, AI Analyst y seguimiento. El proyecto Qualcomm se usó solo como complemento para ampliar la muestra de telemetría; esta presentación trata DevFlight.');
txt(s,'Datos reales.\nConsultas visibles.\nSeguimiento comprobado.',70,185,1100,275,72,C.ink,true);
txt(s,'La demo muestra la cadena completa, desde la actividad del agente hasta una acción registrada en RawTree.',70,490,1080,92,30,C.soft);
txt(s,'El proyecto Qualcomm aportó actividad complementaria para ampliar la muestra de datos.',70,610,1100,45,22,C.muted);
txt(s,'DEMO_FINAL.mp4',70,666,650,28,21,C.lime,true);

for(let i=0;i<p.slides.items.length;i++){
  const png=await p.slides.items[i].export({format:'png',scale:1});
  await fs.writeFile(path.join(buildDir,`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));
}
await (await PresentationFile.exportPptx(p)).save(candidatePath);
const finalization=await finalizePresentation({
  workspaceDir,candidatePath,finalPath,pythonExecutable:runtimePython,
  integrityValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(skillDir,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],
  explicitTotalSlideCount:8,
  requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
  fontPolicy:{basis:'design',families:['Arial','Consolas']},
  verifyArtifactToolImport:true,
  receiptPath:path.join(buildDir,'DevFlight_Pitch.validation.json'),
});
console.log(JSON.stringify({slides:p.slides.items.length,finalPath,finalization}));
