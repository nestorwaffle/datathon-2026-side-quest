import React from 'react';
import {AlertCircle, ArrowUpRight, Check, ChevronLeft, ChevronRight, Database, LoaderCircle, RefreshCw, X} from 'lucide-react';
import type {Row} from './lib/types';
import {formatDate, text} from './lib/format';

export function Badge({children, tone = 'neutral'}: {children: React.ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'error' | 'accent'}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function Spinner({label = 'Cargando…'}: {label?: string}) {
  return <span className="loading-inline" role="status"><LoaderCircle size={15} className="spin"/>{label}</span>;
}

export function Empty({title, children, icon: Icon = Database, action}: {title: string; children?: React.ReactNode; icon?: React.ElementType; action?: React.ReactNode}) {
  return <div className="empty"><div className="empty-icon"><Icon size={24}/></div><h3>{title}</h3>{children && <p>{children}</p>}{action && <div className="empty-action">{action}</div>}</div>;
}

export function Notice({children, tone = 'neutral', title, onClose}: {children: React.ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'error'; title?: string; onClose?: () => void}) {
  const Icon = tone === 'success' ? Check : AlertCircle;
  return <div className={`notice ${tone}`} role={tone === 'error' ? 'alert' : 'status'}><Icon size={17}/><div>{title && <strong>{title}</strong>}<div>{children}</div></div>{onClose && <button className="icon-button" onClick={onClose} aria-label="Cerrar aviso"><X size={16}/></button>}</div>;
}

export function LoadError({error, retry}: {error: string; retry?: () => void}) {
  if (!error) return null;
  return <Notice tone="error" title="No se han podido actualizar los datos">{error}{retry && <button className="text-button" onClick={retry}><RefreshCw size={13}/>Reintentar</button>}</Notice>;
}

export function Panel({title, description, actions, children, className = ''}: {title?: string; description?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string}) {
  return <section className={`panel ${className}`}>{(title || actions) && <div className="panel-heading"><div>{title && <h2>{title}</h2>}{description && <p>{description}</p>}</div>{actions}</div>}{children}</section>;
}

export function Metric({label, value, note, icon: Icon, loading = false, accent = false}: {label: string; value: string; note: string; icon: React.ElementType; loading?: boolean; accent?: boolean}) {
  return <section className={`metric ${accent ? 'metric-accent' : ''}`}><div className="metric-top"><span>{label}</span><Icon size={17}/></div><div className={`metric-value ${loading ? 'loading-value' : ''}`}>{value}</div><p>{note}</p></section>;
}

export interface Column {key: string; title: string; render?: (row: Row) => React.ReactNode; className?: string;}

export function DataTable({rows, columns, empty = 'No hay datos para este alcance', rowKey}: {rows: Row[]; columns: Column[]; empty?: string; rowKey?: (row: Row, index: number) => string}) {
  if (!rows.length) return <Empty title={empty}>Prueba otro período o conecta una fuente de telemetría.</Empty>;
  return <div className="table-scroll"><table><thead><tr>{columns.map(column => <th key={column.key} scope="col" className={column.className}>{column.title}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={rowKey?.(row, index) || `${text(row.event_id || row.id || row.session_id, 'row')}-${index}`}>{columns.map(column => <td key={column.key} className={column.className}>{column.render ? column.render(row) : text(row[column.key], '—')}</td>)}</tr>)}</tbody></table></div>;
}

export function Pagination({page, hasMore, loading, onPage, detail}: {page: number; hasMore?: boolean; loading?: boolean; onPage: (page: number) => void; detail?: string}) {
  return <div className="pagination"><span>{detail || `Página ${page}`}</span><div><button className="button" disabled={page <= 1 || loading} onClick={() => onPage(page - 1)}><ChevronLeft size={15}/>Anterior</button><button className="button" disabled={!hasMore || loading || page >= 10000} onClick={() => onPage(page + 1)}>Siguiente<ChevronRight size={15}/></button></div></div>;
}

export function Updated({at, loading, manual = false}: {at: Date | null; loading: boolean; manual?: boolean}) {
  return <div className="updated-note" aria-live="polite">{loading ? <Spinner label="Consultando RawTree…"/> : at ? <><span className="dot success"/>Consultado {formatDate(at.toISOString())}{manual ? ' · consulta manual' : ' · refresco cada 30 s'}</> : <><span className="dot"/>Esperando consulta</>}</div>;
}

export function DetailsJson({label, value}: {label: string; value: unknown}) {
  return <details className="details-json"><summary>{label}<ArrowUpRight size={13}/></summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}
