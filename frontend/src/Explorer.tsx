import {lazy, Suspense, useEffect, useMemo, useRef, useState} from 'react';
import {BookOpen, Check, ChevronDown, Code2, Download, Filter, Layers3, Play, Save, Table2, X} from 'lucide-react';
import type {Row, Scope} from './lib/types';
import {api, errorMessage, isAbort, useRemote} from './lib/api';
import {FILTER_LABELS, formatDate, text} from './lib/format';
import {Badge, DataTable, Empty, LoadError, Notice, Pagination, Panel, Spinner} from './ui';

const BarChart = lazy(() => import('./Charts').then(module => ({default: module.BarChart})));
interface TableInfo {name: string; fields: string[]; authorized: boolean; state?: string; time_filter_supported?: boolean;}
interface QueryConfig {table: string; fields: string[]; group_by?: string[]; hours: number; page: number; filters: Record<string, string>; offline?: boolean; source_scope?: 'workspace' | 'organization'; source_id?: string;}
interface QueryResult {data: Row[]; sql?: string; source?: string; page?: number; has_more?: boolean; live?: boolean; snapshot_at?: number | string; warning?: string;}
interface SavedView {id: string; name: string; config: QueryConfig;}

function globalFilters(scope: Scope): Record<string, string> {
  return Object.fromEntries(Object.entries(scope).filter(([key, value]) => key in FILTER_LABELS && value !== undefined && value !== '').map(([key, value]) => [key, String(value)]));
}

export default function Explorer({scope, identityKey, refreshToken, dark}: {scope: Scope; identityKey: string; refreshToken: number; dark: boolean}) {
  const tables = useRemote<{items: TableInfo[]}>('/explorer/tables', identityKey, refreshToken);
  const views = useRemote<{items: SavedView[]}>('/views', identityKey, refreshToken);
  const [table, setTable] = useState('dev_all_events');
  const [fields, setFields] = useState<string[]>([]);
  const [group, setGroup] = useState('');
  const [filterField, setFilterField] = useState('session_id');
  const [filterValue, setFilterValue] = useState('');
  const [viewFilters, setViewFilters] = useState<Record<string, string>>({});
  const [offline, setOffline] = useState(false);
  const [applied, setApplied] = useState<QueryConfig | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [resultConfig, setResultConfig] = useState<QueryConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState<Date | null>(null);
  const [saving, setSaving] = useState(false);
  const [showSave, setShowSave] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [notice, setNotice] = useState('');
  const [exporting, setExporting] = useState(false);
  const [revision, setRevision] = useState(0);
  const pendingView = useRef<QueryConfig | null>(null);
  const generation = useRef(0);
  const selected = tables.data?.items.find(item => item.name === table);
  const columns = selected?.fields || [];
  const schemaKey = `${table}:${columns.join('|')}`;
  const scopeKey = JSON.stringify(scope);
  const global = useMemo(() => globalFilters(scope), [scopeKey]);
  const unsupported = columns.length ? Object.keys(global).filter(key => !columns.includes(key)) : [];

  useEffect(() => {
    if (!columns.length) return;
    const saved = pendingView.current?.table === table ? pendingView.current : null;
    const defaults = columns.filter(field => ['timestamp', 'event_id', 'session_id', 'tool', 'status', 'activity_kind', 'provider', 'model', 'source_table', 'origin_user_id'].includes(field)).slice(0, 10);
    const nextFields = saved ? saved.fields.filter(field => columns.includes(field)).slice(0, 12) : defaults.length ? defaults : columns.slice(0, 6);
    const nextGroup = saved?.group_by?.[0] && columns.includes(saved.group_by[0]) ? saved.group_by[0] : '';
    const storedFilters = saved?.filters || {};
    const localFilter = Object.entries(storedFilters).find(([key]) => !Object.hasOwn(global, key) && columns.includes(key));
    setViewFilters(Object.fromEntries(Object.entries(storedFilters).filter(([key]) => key !== localFilter?.[0])));
    setFields(nextFields); setGroup(nextGroup); setFilterField(localFilter?.[0] || (columns.includes('session_id') ? 'session_id' : columns[0])); setFilterValue(localFilter?.[1] || '');
    setApplied({table, fields: nextFields, group_by: nextGroup ? [nextGroup] : [], hours: scope.hours, source_scope: scope.source_scope, ...(saved?.source_id ? {source_id: saved.source_id} : {}), page: 1, filters: {...storedFilters, ...global}, offline: false});
    setResult(null); setResultConfig(null); setOffline(false); pendingView.current = null;
  }, [schemaKey]);

  useEffect(() => {
    setApplied(previous => previous ? {...previous, hours: scope.hours, source_scope: scope.source_scope, page: 1, filters: {...viewFilters, ...(filterValue && columns.includes(filterField) ? {[filterField]: filterValue} : {}), ...global}} : null);
  }, [scopeKey]);

  useEffect(() => {
    if (!applied || !columns.length || unsupported.length) {
      generation.current++;
      if (unsupported.length) { setResult(null); setResultConfig(null); setLoading(false); }
      return;
    }
    const current = ++generation.current;
    const controller = new AbortController();
    setLoading(true); setError('');
    api<QueryResult>('/explorer/query', {body: applied, signal: controller.signal}).then(data => {
      if (generation.current !== current || controller.signal.aborted) return;
      setResult(data); setResultConfig(applied); setUpdated(new Date());
    }).catch(failure => {
      if (!isAbort(failure) && generation.current === current) { setError(errorMessage(failure)); setResult(null); setResultConfig(null); }
    }).finally(() => { if (generation.current === current && !controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [applied, identityKey, refreshToken, revision, schemaKey, unsupported.join('|')]);

  const config = (): QueryConfig => ({table, fields, group_by: group ? [group] : [], hours: scope.hours, source_scope: scope.source_scope, ...(applied?.table === table && applied.source_id ? {source_id: applied.source_id} : {}), page: 1, filters: {...viewFilters, ...(filterValue ? {[filterField]: filterValue} : {}), ...global}, offline});
  const run = () => { setApplied(config()); setRevision(value => value + 1); };
  const save = async () => {
    if (!saveName.trim() || !resultConfig) return;
    setSaving(true); setError('');
    try { await api('/views', {body: {name: saveName.trim(), config: {...resultConfig, page: 1, offline: false}}}); views.refresh(); setShowSave(false); setSaveName(''); setNotice('Vista guardada en tu historial privado.'); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setSaving(false); }
  };
  const loadView = (view: SavedView) => {
    pendingView.current = view.config;
    if (view.config.table !== table) { setTable(view.config.table); return; }
    const nextFields = (view.config.fields || []).filter(field => columns.includes(field)).slice(0, 12);
    const nextGroup = view.config.group_by?.[0] || '';
    const local = Object.entries(view.config.filters || {}).find(([key]) => !Object.hasOwn(global, key));
    setViewFilters(Object.fromEntries(Object.entries(view.config.filters || {}).filter(([key]) => key !== local?.[0])));
    setFields(nextFields); setGroup(nextGroup); setFilterField(local?.[0] || 'session_id'); setFilterValue(local?.[1] || ''); setOffline(false);
    setApplied({...view.config, hours: scope.hours, source_scope: scope.source_scope, filters: {...(view.config.filters || {}), ...global}, fields: nextFields, page: 1, offline: false}); pendingView.current = null;
    setNotice('Vista cargada con el período y los filtros globales actuales.');
  };
  const exportRows = async () => {
    if (!resultConfig) return;
    setExporting(true); setError('');
    try {
      const response = await fetch('/api/explorer/export', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...resultConfig, page: 1})});
      if (!response.ok) { const message = await response.json(); throw Error(typeof message.error === 'string' ? message.error : 'No se ha podido exportar la consulta.'); }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'devflight-' + table + '.csv'; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('CSV descargado: hasta 100 registros de la primera página de la consulta.');
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setExporting(false); }
  };

  const resultColumns = Object.keys(result?.data?.[0] || {}).map(key => ({key, title: key, className: 'mono', render: (row: Row) => text(row[key], 'No reportado')}));
  const chartGroup = resultConfig?.group_by?.[0];
  return <div className="explorer-view"><LoadError error={tables.error || views.error} retry={() => { tables.refresh(); views.refresh(); }}/>{notice && <Notice tone="success" onClose={() => setNotice('')}>{notice}</Notice>}
    <Panel title="Explora los datos de tu espacio" description="Selecciona una tabla, define una agrupación y conserva una consulta reutilizable." actions={<Badge tone="accent"><Code2 size={12}/>RawTree SQL</Badge>}>
      <div className="explorer-toolbar"><label><span><Table2 size={14}/>Tabla</span><select value={table} onChange={event => { setTable(event.target.value); setResult(null); setResultConfig(null); }}>{!tables.data?.items.length && <option value="dev_all_events">Cargando tablas…</option>}{tables.data?.items.map(item => <option key={item.name} value={item.name} disabled={!item.authorized || !item.fields.length}>{item.name}{!item.authorized ? ' · sin autorización' : !item.fields.length ? ' · no disponible' : ''}</option>)}</select></label><label><span><Layers3 size={14}/>Agrupar por</span><select value={group} onChange={event => setGroup(event.target.value)}><option value="">Registros individuales</option>{columns.map(column => <option key={column}>{column}</option>)}</select></label><label className="explorer-filter"><span><Filter size={14}/>Filtro adicional</span><div className="joined-input"><select aria-label="Campo del filtro adicional" value={filterField} onChange={event => setFilterField(event.target.value)}>{columns.map(column => <option key={column}>{column}</option>)}</select><input aria-label="Valor exacto del filtro adicional" placeholder="Valor exacto…" value={filterValue} onChange={event => setFilterValue(event.target.value)}/></div></label></div>
      {Object.keys(viewFilters).length > 0 && <div className="saved-filter-row"><span>Filtros de la vista guardada</span>{Object.entries(viewFilters).map(([key, value]) => <button className="filter-chip" key={key} title={`Quitar ${key} de la próxima consulta`} onClick={() => setViewFilters(previous => Object.fromEntries(Object.entries(previous).filter(([field]) => field !== key)))}><span>{FILTER_LABELS[key] || key}</span><b>{Object.hasOwn(global, key) ? global[key] : value}</b><X size={12}/></button>)}<small>Los filtros globales prevalecen si usan el mismo campo.</small></div>}
      {unsupported.length > 0 && <div className="panel-inset"><Notice tone="warning">Esta tabla no contiene los campos {unsupported.map(key => FILTER_LABELS[key] || key).join(', ')}. Quita esos filtros globales o selecciona otra tabla para evitar una consulta de alcance distinto.</Notice></div>}
      {selected?.time_filter_supported === false && <div className="panel-inset"><Notice tone="warning">Esta tabla no dispone de un campo temporal compatible. El período seleccionado no puede aplicarse; revisa el SQL antes de interpretar sus resultados.</Notice></div>}
      <details className="field-selector"><summary>Campos visibles <Badge>{fields.length}/12</Badge><ChevronDown size={14}/></summary><div>{columns.map(column => <label key={column}><input type="checkbox" checked={fields.includes(column)} disabled={!fields.includes(column) && fields.length >= 12} onChange={event => setFields(event.target.checked ? [...fields, column] : fields.filter(field => field !== column))}/><span>{column}</span></label>)}</div></details>
      <div className="explorer-command"><button className="primary" disabled={loading || !fields.length || !!unsupported.length} onClick={run}>{loading ? <Spinner label="Consultando…"/> : <><Play size={14}/>Ejecutar consulta</>}</button><label className="snapshot-toggle"><input type="checkbox" checked={offline} onChange={event => setOffline(event.target.checked)}/><span>Snapshot verificado</span></label><div className="command-spacer"/><select aria-label="Abrir vista guardada" value="" onChange={event => { const view = views.data?.items.find(item => item.id === event.target.value); if (view) loadView(view); }}><option value="">Vistas guardadas{views.data?.items.length ? ` (${views.data.items.length})` : ''}</option>{views.data?.items.map(view => <option key={view.id} value={view.id}>{view.name}</option>)}</select><button className="button" disabled={!resultConfig} onClick={() => setShowSave(value => !value)}><Save size={14}/>Guardar vista</button></div>
      {showSave && <form className="save-view-form" onSubmit={event => { event.preventDefault(); void save(); }}><BookOpen size={16}/><label className="sr-only" htmlFor="saved-view-name">Nombre de la vista</label><input id="saved-view-name" placeholder="Nombre de tu vista privada" autoFocus value={saveName} maxLength={120} onChange={event => setSaveName(event.target.value)}/><button className="primary" disabled={saving || !saveName.trim()}><Check size={14}/>{saving ? 'Guardando…' : 'Guardar'}</button><button type="button" className="text-button" onClick={() => setShowSave(false)}>Cancelar</button></form>}
    </Panel>
    <LoadError error={error} retry={run}/>
    {result?.warning && <Notice tone="warning">{result.warning}</Notice>}
    <Panel title={chartGroup ? `Resultados por ${chartGroup}` : 'Registros de la consulta'} description={result ? <>{result.source || 'RawTree'} · {result.live === false ? `snapshot histórico ${formatDate(result.snapshot_at)}` : `consulta ${formatDate(updated?.toISOString())}`} · hasta 100 filas por página</> : 'La consulta conserva sus filtros y el SQL ejecutado.'} actions={<button className="button" onClick={() => void exportRows()} disabled={!resultConfig || exporting}><Download size={14}/>{exporting ? 'Exportando…' : 'Exportar primera página'}</button>}>
      {result?.live === false && <div className="panel-inset"><Notice tone="warning">Estás viendo un resultado histórico verificado para esta consulta. No representa una lectura en directo.</Notice></div>}
      {loading && !result ? <div className="section-loading"><Spinner label="Consultando filas autorizadas…"/></div> : result ? <>{chartGroup && result.data.length > 0 && <Suspense fallback={<div className="section-loading"><Spinner/></div>}><BarChart rows={result.data} labelKey={chartGroup} dark={dark}/></Suspense>}<DataTable rows={result.data || []} columns={resultColumns}/><Pagination page={result.page || applied?.page || 1} hasMore={result.has_more} loading={loading} onPage={page => setApplied(previous => previous ? {...previous, page} : null)} detail={`Página ${result.page || applied?.page || 1} · ${result.data.length} filas${result.has_more ? ' · hay más resultados' : ''}`}/></> : <Empty icon={Table2} title={tables.loading ? 'Descubriendo el esquema' : 'Selecciona los datos que quieres explorar'}>El período y los filtros de la cabecera se aplican a esta consulta.</Empty>}
      <details className="sql-evidence"><summary><Code2 size={15}/>SQL y definiciones<ChevronDown size={14}/></summary><pre>{result?.sql || 'La consulta SQL aparecerá aquí después de ejecutarse.'}</pre><p>Una fila es un registro recibido, no necesariamente una petición al modelo. Los importes y tokens no reportados se muestran como desconocidos. El CSV contiene hasta 100 filas de la primera página.</p></details>
    </Panel>
  </div>;
}
