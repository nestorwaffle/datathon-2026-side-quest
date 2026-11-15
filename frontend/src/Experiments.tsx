import {lazy, Suspense, useMemo, useState} from 'react';
import {ArrowUpRight, CheckCircle2, FlaskConical, Layers3, Target} from 'lucide-react';
import type {ExperimentResult, Row, Scope} from './lib/types';
import {scopeQuery, useRemote} from './lib/api';
import {finite, formatDate, formatNumber, formatPercent, text} from './lib/format';
import {Badge, DataTable, DetailsJson, Empty, LoadError, Metric, Notice, Panel, Spinner, Updated} from './ui';

const BarChart = lazy(() => import('./Charts').then(module => ({default: module.BarChart})));
const comparisonKeys = ['dataset', 'split', 'suite_version', 'hardware'];
const cohortKey = (row: Row) => comparisonKeys.map(key => text(row[key], 'No reportado')).join(' · ');

export default function Experiments({scope, identityKey, refreshToken, dark, onAnalyze}: {scope: Scope; identityKey: string; refreshToken: number; dark: boolean; onAnalyze: () => void}) {
  const remote = useRemote<ExperimentResult>('/experiments' + scopeQuery(scope), identityKey, refreshToken, 30000);
  const [cohort, setCohort] = useState('');
  const rows = remote.data?.items || [];
  const groups = useMemo(() => [...new Set(rows.map(cohortKey))], [rows]);
  const activeCohort = groups.includes(cohort) ? cohort : groups[0] || '';
  const selected = rows.filter(row => cohortKey(row) === activeCohort);
  const chartRows = selected.filter(row => finite(row.accuracy) !== null).map(row => ({...row, label: `${text(row.recipe || row.variant, 'Sin receta')} · ${text(row.run_id, 'sin ID').slice(0, 8)}`}));
  const summary = remote.data?.summary;
  const breakdown = remote.data?.breakdown || [];
  const comparable = selected.every(row => comparisonKeys.every(key => row[key] !== undefined && row[key] !== null && row[key] !== ''));
  return <><LoadError error={remote.error} retry={remote.refresh}/><Updated at={remote.updated} loading={remote.loading}/><div className="metrics-grid"><Metric label="Ejecuciones registradas" value={formatNumber(summary?.runs ?? (remote.data ? rows.length : null), 0)} note="Evaluaciones encontradas en la fuente" icon={FlaskConical} loading={remote.loading}/><Metric label="Grupos comparables" value={formatNumber(summary?.comparable_groups, 0)} note="Según el contexto de evaluación" icon={Layers3} loading={remote.loading}/><Metric label="Última exactitud reportada" value={formatPercent(summary?.latest_accuracy)} note="No implica la mejor configuración" icon={Target} loading={remote.loading}/><Metric label="Resultados desglosados" value={remote.data ? formatNumber(breakdown.length, 0) : '—'} note="Mediciones por categoría disponibles" icon={CheckCircle2} loading={remote.loading}/></div>
    {!remote.loading && !rows.length ? <Panel><Empty icon={FlaskConical} title="Todavía no hay evaluaciones visibles">Cuando una ejecución publique resultados compatibles en RawTree, podrás comparar recetas, conjuntos y categorías desde aquí.</Empty></Panel> : <>
      <Panel title="Compara el mismo contexto" description="Conjunto, partición, versión de evaluación y hardware mantienen la comparación interpretable." actions={<button className="button" onClick={onAnalyze}>Investigar con IA<ArrowUpRight size={14}/></button>}><div className="experiment-controls"><label>Contexto de evaluación<select value={activeCohort} onChange={event => setCohort(event.target.value)}>{groups.map(group => <option key={group}>{group}</option>)}</select></label><Badge>{selected.length} ejecuciones</Badge></div>{selected.length > 0 && !comparable && <div className="panel-inset"><Notice tone="warning">Parte del contexto no está reportado. Estas mediciones se muestran juntas para explorarlas; su comparabilidad no está demostrada.</Notice></div>}{chartRows.length ? <Suspense fallback={<div className="section-loading"><Spinner/></div>}><BarChart rows={chartRows} labelKey="label" valueKey="accuracy" dark={dark} percent/></Suspense> : <Empty title="No hay exactitud reportada para este contexto">Los valores ausentes no se convierten en cero.</Empty>}
        <DataTable rows={selected} columns={[{key: 'recipe', title: 'Receta / variante', render: row => <strong>{text(row.recipe || row.variant)}</strong>}, {key: 'accuracy', title: 'Exactitud', render: row => formatPercent(row.accuracy)}, {key: 'count', title: 'Casos', render: row => formatNumber(row.count, 0)}, {key: 'seconds', title: 'Duración', render: row => finite(row.seconds) === null ? '—' : `${formatNumber(row.seconds)} s`}, {key: 'tokens', title: 'Tokens', render: row => formatNumber(row.tokens, 0)}, {key: 'run_id', title: 'Ejecución', className: 'mono'}, {key: 'timestamp', title: 'Fecha', render: row => formatDate(row.timestamp)}]}/>
      </Panel>
      {breakdown.length > 0 && <Panel title="Desglose de los resultados" description="Mediciones publicadas por categoría; no se generan resultados ausentes."><DataTable rows={breakdown} columns={[{key: 'recipe', title: 'Receta'}, {key: 'dimension', title: 'Dimensión'}, {key: 'value', title: 'Categoría'}, {key: 'accuracy', title: 'Exactitud', render: row => formatPercent(row.accuracy)}, {key: 'count', title: 'Casos', render: row => formatNumber(row.count, 0)}, {key: 'run_id', title: 'Ejecución', className: 'mono'}]}/></Panel>}
      <Panel title="Todas las ejecuciones" description="Trazabilidad de los resultados disponibles en el alcance seleccionado."><DataTable rows={rows} columns={[{key: 'recipe', title: 'Receta', render: row => text(row.recipe || row.variant)}, {key: 'dataset', title: 'Dataset'}, {key: 'split', title: 'Partición'}, {key: 'suite_version', title: 'Evaluación'}, {key: 'hardware', title: 'Hardware'}, {key: 'accuracy', title: 'Exactitud', render: row => formatPercent(row.accuracy)}, {key: 'source_table', title: 'Tabla de origen', className: 'mono'}]}/></Panel>
    </>}{remote.data?.coverage && <DetailsJson label="Cobertura de los resultados" value={remote.data.coverage}/>}</>;
}
