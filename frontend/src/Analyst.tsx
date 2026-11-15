import {useEffect, useMemo, useRef, useState} from 'react';
import {ArrowDown, ArrowUpRight, BookOpen, Check, ChevronDown, Code2, Database, FileSearch, History, LoaderCircle, MessageSquare, Plus, RefreshCw, Send, ShieldCheck, Sparkles, Square, X} from 'lucide-react';
import type {AnalystStatus, Evidence, Investigation, Row, Scope} from './lib/types';
import {ApiError, api, errorMessage, isAbort, useRemote} from './lib/api';
import {formatDate, formatDuration, formatNumber, isActiveStatus, scopeLabel, statusLabel, text} from './lib/format';
import {Badge, DataTable, Empty, LoadError, Notice, Spinner} from './ui';
import Markdown from './Markdown';

interface Submission {question: string; scope: Scope; conversation_id?: string; request_id: string;}
interface Conversation {id: string; title: string; records: Investigation[]; last: Investigation;}

const phaseLabels: Record<string, string> = {
  queued: 'Esperando un turno disponible', preparing: 'Preparando el contexto autorizado',
  model: 'El modelo está decidiendo el siguiente paso', query: 'Consultando evidencia en RawTree',
  synthesis: 'Redactando una respuesta con la evidencia', persisting: 'Guardando la investigación',
  completed: 'Investigación completada', cancelling: 'Deteniendo los próximos pasos',
};

function EvidenceCard({evidence, index}: {evidence: Evidence; index: number}) {
  const rows = Array.isArray(evidence.data) ? evidence.data : [];
  const columns = rows[0] ? Object.keys(rows[0]).slice(0, 7).map(key => ({key, title: key, render: (row: Row) => text(row[key], '—')})) : [];
  return <details className="evidence-card"><summary><span className="evidence-number">{index + 1}</span><div><strong>{evidence.tool || 'Consulta RawTree'}</strong><span>{evidence.source || 'Fuente registrada'} · {rows.length} {rows.length === 1 ? 'fila' : 'filas'} devueltas</span></div>{evidence.status === 'error' && <Badge tone="error">Error</Badge>}<ChevronDown size={15}/></summary><div className="evidence-body">
    {typeof evidence.error === 'string' && <Notice tone="error">{evidence.error}</Notice>}
    {!!evidence.model_context_truncated && <Notice tone="warning">El modelo recibió {formatNumber(evidence.rows_in_model_context, 0)} de las {rows.length} filas para respetar su límite de contexto. El resultado completo se conserva en esta evidencia.</Notice>}
    {evidence.arguments && <div className="evidence-arguments">{Object.entries(evidence.arguments).map(([key, value]) => <span key={key}><b>{key}</b> {text(value, '—')}</span>)}</div>}
    {evidence.sql ? <div className="sql-block"><div><Code2 size={14}/>SQL ejecutado</div><pre><code>{evidence.sql}</code></pre></div> : <p className="muted small">Esta herramienta no ha registrado una consulta SQL.</p>}
    {rows.length > 0 && <div className="evidence-results"><DataTable rows={rows.slice(0, 8)} columns={columns}/>{rows.length > 8 && <p className="table-note">Vista previa de 8 de {rows.length} filas. El resultado completo está disponible abajo.</p>}</div>}
    <details className="raw-evidence"><summary>Ver respuesta completa de la herramienta</summary><pre>{JSON.stringify(evidence, null, 2)}</pre></details>
  </div></details>;
}

function InvestigationMessage({record, onSave, saving, saved, loadingDetails}: {record: Investigation; onSave: () => void; saving: boolean; saved: boolean; loadingDetails: boolean}) {
  const active = !record.read_only && isActiveStatus(record.status);
  const evidence = record.evidence || [];
  const events = record.progress_events || [];
  const lastEvent = events[events.length - 1];
  const phase = phaseLabels[record.phase || record.status] || lastEvent?.message || 'Recopilando evidencia';
  const complete = record.status === 'completed';
  return <article className="chat-turn" aria-label="Pregunta y respuesta del analista">
    <div className="user-message"><div className="user-message-label">Tú <span>{formatDate(record.created_at || record.timestamp)}</span></div><p>{record.question}</p><div className="message-scope"><Database size={12}/>{scopeLabel(record.scope)}</div></div>
    <div className="assistant-message"><div className="assistant-avatar"><Sparkles size={18}/></div><div className="assistant-content"><div className="assistant-byline"><strong>DevFlight Analyst</strong>{record.model && <span className="model-pill">{record.model}</span>}<Badge tone={record.read_only ? 'neutral' : complete ? 'success' : active ? 'accent' : 'warning'}>{record.read_only ? 'Histórico · solo lectura' : statusLabel(record.status)}</Badge></div>
      {record.historical_scope_unverified && <Notice tone="warning">El origen y el alcance de esta investigación histórica no están verificados. Se conserva para consulta, sin reutilizarla como contexto de una inferencia nueva.</Notice>}
      {record.journal_unavailable && <Notice tone="error">El diario persistente no está disponible. Este resultado se ha recuperado de un estado temporal en memoria; su guardado todavía no está confirmado.</Notice>}
      {active && <div className="analyst-progress" role="status" aria-live="polite"><LoaderCircle size={16} className="spin"/><div><strong>{record.status === 'cancelling' ? 'Deteniendo los próximos pasos' : phase}</strong><span>{record.query_count || 0} consultas · {record.iterations || 0} pasos del modelo{record.usage?.total_tokens !== undefined ? ` · ${formatNumber(record.usage.total_tokens)} tokens reportados` : ''}</span></div></div>}
      {record.conclusion && <Markdown>{record.conclusion}</Markdown>}
      {!record.conclusion && record.partial_summary && <Markdown>{record.partial_summary}</Markdown>}
      {loadingDetails && !active && !record.conclusion && <div className="analyst-progress" role="status"><LoaderCircle size={15} className="spin"/><strong>Recuperando la respuesta y su evidencia…</strong></div>}
      {!loadingDetails && !active && !record.conclusion && <Notice tone={record.status === 'failed' ? 'error' : 'warning'}>No hay una conclusión completa para esta investigación. {record.status === 'interrupted' ? 'El servicio se reinició. Puedes continuar con una nueva pregunta; no se ha repetido automáticamente la inferencia.' : 'La evidencia recopilada se conserva a continuación.'}</Notice>}
      {record.error && <Notice tone="error">{record.error}</Notice>}
      {record.truncated && <Notice tone="warning">La respuesta alcanzó el límite de salida y puede estar incompleta. Puedes pedir una continuación usando la evidencia ya recopilada.</Notice>}
      {evidence.length > 0 && <div className="evidence-section"><div className="section-eyebrow"><FileSearch size={14}/>Evidencia consultada <span>{evidence.length}</span></div>{evidence.map((item, index) => <EvidenceCard key={index} evidence={item} index={index}/>)}</div>}
      {events.length > 0 && <details className="tool-activity"><summary><History size={13}/>Actividad de la investigación<ChevronDown size={13}/></summary><ol>{events.map((event, index) => <li key={index}><span className="timeline-point"/><div><strong>{event.message || phaseLabels[event.phase || ''] || event.phase}</strong><small>{formatDate(event.at)}</small></div></li>)}</ol></details>}
      {!!record.calls?.length && <details className="raw-evidence"><summary>Llamadas al modelo y consumo reportado</summary><pre>{JSON.stringify(record.calls, null, 2)}</pre></details>}
      {record.context_bounded && <p className="context-note">Contexto conversacional acotado: {formatNumber(record.conversation_context_turns, 0)} turnos previos utilizados.</p>}
      {!active && <div className="answer-footer"><span>{record.query_count || evidence.length} consultas{record.seconds !== undefined ? ` · ${formatDuration(record.seconds)}` : ''}{record.usage?.total_tokens !== undefined ? ` · ${formatNumber(record.usage.total_tokens)} tokens` : ''}{record.finish_reason && record.finish_reason !== 'stop' ? ` · ${record.finish_reason}` : ''}</span>{!record.read_only && evidence.some(item => item.status !== 'error') && <button className="text-button" disabled={saving || saved} onClick={onSave}>{saved ? <Check size={14}/> : <BookOpen size={14}/>} {saved ? 'Vista guardada' : saving ? 'Guardando…' : 'Guardar vista de seguimiento'}</button>}</div>}
    </div></div>
  </article>;
}

export default function Analyst({scope, identityKey, refreshToken, role}: {scope: Scope; identityKey: string; refreshToken: number; role: string}) {
  const history = useRemote<{items: Investigation[]}>('/investigations', identityKey, refreshToken, 30000);
  const configuration = useRemote<AnalystStatus>('/analyst/status', identityKey, refreshToken, 60000);
  const [localRecords, setLocalRecords] = useState<Record<string, Investigation>>({});
  const [pendingDetails, setPendingDetails] = useState<string[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [question, setQuestion] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [pending, setPending] = useState<Submission | null>(null);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [notice, setNotice] = useState('');
  const [mobileHistory, setMobileHistory] = useState(false);
  const [historySearch, setHistorySearch] = useState('');
  const [savingId, setSavingId] = useState('');
  const [saved, setSaved] = useState<Set<string>>(() => new Set());
  const [cancelBusy, setCancelBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [connectionNote, setConnectionNote] = useState('');
  const submissionLock = useRef(false);
  const mounted = useRef(true);
  const submitController = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; submitController.current?.abort(); }; }, []);

  const allRecords = useMemo(() => {
    const merged = new Map<string, Investigation>();
    for (const record of history.data?.items || []) merged.set(record.id, record);
    for (const record of Object.values(localRecords)) merged.set(record.id, record);
    return [...merged.values()].sort((a, b) => String(a.created_at || a.timestamp || '').localeCompare(String(b.created_at || b.timestamp || '')));
  }, [history.data, localRecords]);
  const conversations = useMemo(() => {
    const grouped = new Map<string, Conversation>();
    for (const record of allRecords) {
      const id = record.conversation_id || record.id;
      const group = grouped.get(id);
      if (group) { group.records.push(record); group.last = record; }
      else grouped.set(id, {id, title: record.question || 'Investigación', records: [record], last: record});
    }
    return [...grouped.values()].reverse();
  }, [allRecords]);
  const current = conversations.find(conversation => conversation.id === conversationId);
  const messages = current?.records || [];
  const activeRecords = allRecords.filter(record => !record.read_only && isActiveStatus(record.status));
  // An idempotent POST may acknowledge an already terminal job without its payload.
  // Always retrieve that job once, even when it no longer needs progress polling.
  const activeKey = [...new Set([...activeRecords.map(record => record.id), ...pendingDetails])].sort().join('|');
  const currentJob = messages.find(record => !record.read_only && isActiveStatus(record.status));
  const historicalReadOnly = messages.some(record => record.read_only || record.context_eligible === false);
  const awaitingDetails = messages.some(record => pendingDetails.includes(record.id));

  useEffect(() => {
    if (!activeKey) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ids = activeKey.split('|');
    const poll = async () => {
      const results = await Promise.allSettled(ids.map(id => api<Investigation>('/investigations/' + encodeURIComponent(id), {signal: controller.signal})));
      if (controller.signal.aborted) return;
      let failed = '';
      for (const result of results) {
        if (result.status === 'fulfilled') {
          setLocalRecords(records => ({...records, [result.value.id]: result.value}));
          setPendingDetails(ids => ids.filter(id => id !== result.value.id));
        }
        else if (!isAbort(result.reason)) failed = errorMessage(result.reason);
      }
      setPollError(failed);
      timer = setTimeout(poll, failed ? 4000 : 1500);
    };
    void poll();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [activeKey, identityKey, refreshToken]);

  useEffect(() => { if (conversationId) bottom.current?.scrollIntoView({behavior: 'smooth', block: 'nearest'}); }, [conversationId, messages.length]);

  const beginConversation = () => { setConversationId(null); setQuestion(''); setError(''); setMobileHistory(false); input.current?.focus(); };
  const submit = async (retry?: Submission) => {
    if (submissionLock.current || currentJob || (!retry && !question.trim())) return;
    const request: Submission = retry || {question: question.trim(), scope: {...scope}, ...(conversationId ? {conversation_id: conversationId} : {}), request_id: crypto.randomUUID()};
    submissionLock.current = true; setSubmitting(true); setError(''); setPending(request);
    const controller = new AbortController(); submitController.current = controller;
    try {
      const response = await api<Partial<Investigation> & {id: string; status: string}>('/investigations', {body: request, signal: controller.signal});
      if (!mounted.current || controller.signal.aborted) return;
      const record: Investigation = {question: request.question, scope: request.scope, timestamp: new Date().toISOString(), ...response};
      setLocalRecords(records => ({...records, [record.id]: record}));
      setPendingDetails(ids => [...new Set([...ids, record.id])]);
      setConversationId(record.conversation_id || record.id); setQuestion(''); setPending(null); setMobileHistory(false);
      history.refresh();
    } catch (failure) {
      if (!isAbort(failure) && mounted.current) {
        setError(errorMessage(failure));
        if (failure instanceof ApiError && failure.status >= 400 && failure.status < 500) setPending(null);
      }
    } finally {
      submissionLock.current = false;
      if (mounted.current) setSubmitting(false);
    }
  };

  const cancel = async () => {
    if (!currentJob || cancelBusy) return;
    setCancelBusy(true); setError('');
    try {
      const response = await api<Partial<Investigation>>('/investigations/' + encodeURIComponent(currentJob.id) + '/cancel', {body: {}});
      if (mounted.current) setLocalRecords(records => ({...records, [currentJob.id]: {...currentJob, ...response, status: response.status || 'cancelling'}}));
    } catch (failure) { if (mounted.current) setError(errorMessage(failure)); }
    finally { if (mounted.current) setCancelBusy(false); }
  };

  const saveView = async (record: Investigation) => {
    setSavingId(record.id); setNotice(''); setError('');
    try {
      const action = await api<{status?: string}>('/investigations/' + encodeURIComponent(record.id) + '/followup-view', {body: {}});
      if (mounted.current) {
        setSaved(previous => new Set(previous).add(record.id));
        setNotice(action.status === 'verified' ? 'Vista de seguimiento guardada y comprobada con RawTree. Puedes abrirla desde las vistas guardadas del Data Explorer.' : 'Vista de seguimiento guardada. Su comprobación con RawTree está pendiente; puedes consultarla en Data Explorer.');
      }
    } catch (failure) { if (mounted.current) setError(errorMessage(failure)); }
    finally { if (mounted.current) setSavingId(''); }
  };

  const checkConnection = async () => {
    setChecking(true); setError(''); setConnectionNote('');
    try {
      const result = await api<{model_available: boolean; model: string}>('/analyst/check', {body: {}});
      if (mounted.current) setConnectionNote(result.model_available ? `Conexión accesible y ${result.model} disponible en el catálogo. Esta comprobación no ha ejecutado una inferencia.` : `Conexión accesible, pero ${result.model} no aparece en el catálogo. Revisa el modelo configurado.`);
    } catch (failure) { if (mounted.current) setError(errorMessage(failure)); }
    finally { if (mounted.current) setChecking(false); }
  };
  const unavailable = configuration.data?.configured === false || configuration.data?.configuration_valid === false || configuration.data?.rawtree_configured === false;
  const blocked = role === 'viewer' || unavailable || submitting || !!currentJob || !!pending || historicalReadOnly || awaitingDetails;
  const starters = [
    {icon: FileSearch, title: 'Entender los fallos', question: '¿Dónde se concentran los fallos en este período? Compara agentes y herramientas, investiga las sesiones relevantes y cita evidencia concreta.'},
    {icon: Database, title: 'Explorar el espacio', question: 'Explora las tablas disponibles de este espacio RawTree. Explica qué datos contienen, qué cobertura tienen y qué preguntas podemos responder.'},
    {icon: ArrowUpRight, title: 'Comparar experimentos', question: 'Revisa los experimentos disponibles. Compara resultados compatibles, separa conjuntos de evaluación distintos y propón la siguiente comprobación basada en evidencia.'},
  ];

  return <div className="analyst-layout">
    <aside className={`conversation-sidebar ${mobileHistory ? 'mobile-visible' : ''}`} aria-label="Historial del analista"><div className="conversation-heading"><span><MessageSquare size={16}/>Conversaciones</span><button className="icon-button mobile-only" aria-label="Cerrar historial" onClick={() => setMobileHistory(false)}><X size={16}/></button></div><button className="button new-conversation" onClick={beginConversation} disabled={submitting || !!pending}><Plus size={16}/>Nueva conversación</button><p className="history-privacy"><ShieldCheck size={12}/>Tu historial privado · todos los períodos</p><label className="sr-only" htmlFor="history-search">Buscar conversaciones</label><input className="history-search" id="history-search" placeholder="Buscar en el historial…" value={historySearch} onChange={event => setHistorySearch(event.target.value)}/>
      <div className="conversation-list">{history.loading && !conversations.length ? <div className="conversation-loading"><Spinner/></div> : conversations.filter(conversation => conversation.title.toLowerCase().includes(historySearch.toLowerCase())).map(conversation => <button key={conversation.id} className={`conversation-item ${conversation.id === conversationId ? 'selected' : ''}`} onClick={() => { setConversationId(conversation.id); setMobileHistory(false); }}><div>{isActiveStatus(conversation.last.status) ? <LoaderCircle size={13} className="spin"/> : <MessageSquare size={13}/>}<strong>{conversation.title}</strong></div><span>{formatDate(conversation.last.created_at || conversation.last.timestamp)} · {conversation.records.length} {conversation.records.length === 1 ? 'pregunta' : 'preguntas'}</span></button>)}{!history.loading && !conversations.length && <p className="history-empty">Tus investigaciones aparecerán aquí. Una nueva pregunta inicia una conversación.</p>}</div>
      {history.error && <div className="history-error"><span>{history.error}</span><button className="text-button" onClick={history.refresh}>Reintentar</button></div>}<div className="conversation-foot"><Database size={14}/><span>La evidencia procede del espacio RawTree autorizado.</span></div>
    </aside>
    <section className="analyst-workspace" aria-label="Conversación con AI Analyst"><header className="analyst-header"><div className="analyst-title"><button className="icon-button mobile-only" onClick={() => setMobileHistory(true)} aria-label="Abrir historial"><History size={18}/></button><div className="assistant-avatar"><Sparkles size={19}/></div><div><h2>AI Analyst</h2><p>Pregunta. Investiga. Sigue la evidencia.</p></div></div><div className="analyst-model"><span className={`dot ${configuration.data?.configured ? 'success' : 'warning'}`}/>{configuration.loading && !configuration.data ? 'Comprobando configuración' : configuration.data?.model || 'Modelo sin configurar'}<span>{configuration.data?.configured ? 'Configurado' : 'Revisar conexión'}</span></div></header>
      {configuration.error && <div className="chat-notices"><LoadError error={configuration.error} retry={configuration.refresh}/></div>}
      {!unavailable && role !== 'viewer' && <div className="connection-check"><span>{connectionNote || 'La configuración está disponible. La conectividad todavía no se ha comprobado desde esta vista.'}</span><button className="text-button" onClick={() => void checkConnection()} disabled={checking}>{checking ? <LoaderCircle size={12} className="spin"/> : <RefreshCw size={12}/>}Comprobar conexión</button></div>}
      {unavailable && <div className="chat-notices"><Notice tone="warning" title="Revisa las conexiones para iniciar una investigación">Falta una conexión válida con el modelo o la lectura de RawTree. Revisa RAWTREE_READ_KEY, HELMCODE_API_KEY, HELMCODE_BASE_URL y HELMCODE_MODEL en tu configuración local y reinicia el servicio.<button className="text-button" onClick={configuration.refresh}><RefreshCw size={13}/>Comprobar configuración</button></Notice></div>}
      {role === 'viewer' && <div className="chat-notices"><Notice>Tu acceso es de lectura. Puedes consultar tus investigaciones disponibles; iniciar una nueva requiere un rol autorizado.</Notice></div>}
      {historicalReadOnly && <div className="chat-notices"><Notice>Esta conversación histórica es de solo lectura. Inicia otra conversación para analizar la fuente y el alcance actuales.<button className="text-button" onClick={beginConversation}><Plus size={12}/>Crear una conversación nueva</button></Notice></div>}
      <div className="chat-scroll" aria-busy={!!currentJob}>
        {!messages.length && <div className="analyst-welcome"><div className="welcome-mark"><Sparkles size={32}/><span/></div><span className="eyebrow">INTELIGENCIA CON EVIDENCIA</span><h3>Tu espacio RawTree,<br/><em>una conversación más claro.</em></h3><p>El analista elige herramientas, consulta tus datos y explica lo que encuentra. Cada respuesta conserva sus consultas y resultados.</p><div className="starter-grid">{starters.map(starter => <button key={starter.title} className="starter-card" onClick={() => { setQuestion(starter.question); input.current?.focus(); }}><starter.icon size={19}/><strong>{starter.title}</strong><ArrowUpRight size={14}/></button>)}</div><div className="welcome-note"><ShieldCheck size={13}/>Las inferencias empiezan cuando envías una pregunta. Los valores desconocidos se mantienen como desconocidos.</div></div>}
        {messages.map(record => <InvestigationMessage key={record.id} record={record} onSave={() => void saveView(record)} saving={savingId === record.id} saved={saved.has(record.id)} loadingDetails={pendingDetails.includes(record.id)}/>)}
        <div ref={bottom}/>
      </div>
      <div className="chat-bottom">{notice && <Notice tone="success" onClose={() => setNotice('')}>{notice}</Notice>}{pollError && <Notice tone="warning" title="Se ha perdido temporalmente el estado">{pollError} Se volverá a consultar la misma investigación; no se lanzará otra inferencia.</Notice>}{error && <Notice tone="error">{error}{pending && !submitting && <button className="text-button" onClick={() => void submit(pending)}><RefreshCw size={13}/>Comprobar o reintentar la misma solicitud</button>}</Notice>}
        <form className={`chat-composer ${currentJob ? 'working' : ''}`} onSubmit={event => { event.preventDefault(); if (!blocked) void submit(); }}><div className="composer-scope"><Database size={13}/><span>{scopeLabel(scope)}</span><Badge tone="neutral">Alcance de la próxima pregunta</Badge></div><label className="sr-only" htmlFor="analyst-question">Pregunta al analista</label><textarea ref={input} id="analyst-question" value={question} onChange={event => setQuestion(event.target.value)} placeholder={conversationId ? 'Continúa la investigación o pide una comparación…' : '¿Qué quieres entender de tus agentes y experimentos?'} maxLength={2000} disabled={blocked} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!blocked && question.trim()) void submit(); } }}/><div className="composer-footer"><span>{question.length}/2000 <span className="composer-keyboard">· Enter para enviar · Mayús + Enter para nueva línea</span></span>{currentJob ? <button className="button" type="button" onClick={() => void cancel()} disabled={cancelBusy || currentJob.status === 'cancelling'} title="Detiene los próximos pasos. La llamada en curso puede terminar."><Square size={13}/>{currentJob.status === 'cancelling' ? 'Deteniendo…' : 'Detener'}</button> : <button className="primary" type="submit" disabled={blocked || !question.trim()}>{submitting ? <LoaderCircle size={15} className="spin"/> : <Send size={15}/>}<span>{submitting ? 'Enviando…' : 'Preguntar'}</span></button>}</div></form>
        <p className="analyst-disclaimer"><ShieldCheck size={11}/>Conclusiones basadas en la cobertura disponible. Comprueba la evidencia antes de actuar.{messages.length > 2 && <button className="text-button" onClick={() => bottom.current?.scrollIntoView({behavior: 'smooth', block: 'nearest'})}><ArrowDown size={12}/>Ir al final</button>}</p>
      </div>
    </section>
  </div>;
}
