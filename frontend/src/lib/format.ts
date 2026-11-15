import type {Scope} from './types';

export function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === '' || !['number', 'string'].includes(typeof value)) return null;
  const number = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

export function formatNumber(value: unknown, decimals = 1): string {
  const number = finite(value);
  return number === null ? '—' : new Intl.NumberFormat('es-ES', {maximumFractionDigits: decimals}).format(number);
}

export function formatCompact(value: unknown): string {
  const number = finite(value);
  return number === null ? '—' : new Intl.NumberFormat('es-ES', {notation: Math.abs(number) >= 100000 ? 'compact' : 'standard', maximumFractionDigits: 1}).format(number);
}

export function formatMoney(value: unknown): string {
  const number = finite(value);
  return number === null ? '—' : new Intl.NumberFormat('es-ES', {style: 'currency', currency: 'USD', maximumFractionDigits: 4}).format(number);
}

export function formatPercent(value: unknown): string {
  const number = finite(value);
  return number === null ? '—' : new Intl.NumberFormat('es-ES', {style: 'percent', maximumFractionDigits: 1}).format(number);
}

export function formatDate(value: unknown): string {
  if (value === undefined || value === null || value === '') return 'Sin registrar';
  const parsed = typeof value === 'number' ? new Date(value * (value < 1e12 ? 1000 : 1)) : new Date(String(value));
  return Number.isNaN(parsed.getTime()) ? 'Fecha no disponible' : parsed.toLocaleString('es-ES', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'});
}

export function formatDuration(value: unknown): string {
  const seconds = finite(value);
  if (seconds === null) return '—';
  if (seconds < 60) return `${formatNumber(seconds, 0)} s`;
  if (seconds < 3600) return `${formatNumber(seconds / 60, 1)} min`;
  return `${formatNumber(seconds / 3600, 1)} h`;
}

export function text(value: unknown, fallback = 'Sin identificar'): string {
  return value === null || value === undefined || value === '' ? fallback : typeof value === 'object' ? JSON.stringify(value) : String(value);
}

export function totalTokens(row: Record<string, unknown>): number | null {
  const input = finite(row.input_tokens), output = finite(row.output_tokens);
  return input === null && output === null ? null : (input || 0) + (output || 0);
}

export const FILTER_LABELS: Record<string, string> = {
  run_id: 'Ejecución', session_id: 'Sesión', provider: 'Proveedor', model: 'Modelo',
  origin_user_id: 'Emisor', agent: 'Agente', activity_kind: 'Tipo de actividad', team_id: 'Equipo', project_id: 'Proyecto',
};

export function scopeLabel(scope?: Partial<Scope> | null): string {
  if (!scope) return 'Alcance no registrado';
  const hours = scope.hours ?? 24;
  const period = hours === 0 ? 'Todo el historial' : hours === 1 ? 'Última hora' : hours < 24 ? `Últimas ${hours} horas` : hours === 24 ? 'Últimas 24 h' : `Últimos ${hours / 24} días`;
  const filters = Object.entries(scope).filter(([key, value]) => key in FILTER_LABELS && value !== undefined && value !== '');
  return [scope.source_scope === 'organization' ? 'Organización autorizada' : 'Espacio RawTree compartido', period, ...filters.map(([key, value]) => `${FILTER_LABELS[key]}: ${value}`)].join(' · ');
}

export const ACTIVE_STATUSES = new Set(['queued', 'running', 'cancelling']);
export function isActiveStatus(status: string): boolean { return ACTIVE_STATUSES.has(status); }

export function statusLabel(status: string): string {
  return ({queued: 'En cola', running: 'Investigando', cancelling: 'Deteniendo', completed: 'Completada', failed: 'Error', cancelled: 'Cancelada', interrupted: 'Interrumpida', timeout: 'Tiempo agotado', truncated: 'Respuesta incompleta', persistence_failed: 'Error de guardado', token_budget_exhausted: 'Límite de tokens', query_budget_exhausted: 'Límite de consultas', iteration_budget_exhausted: 'Límite de pasos', no_tool_evidence: 'Sin evidencia suficiente'} as Record<string, string>)[status] || status;
}

export function safeHref(href: string): string | null {
  try { const url = new URL(href); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}
