import {useCallback, useEffect, useRef, useState} from 'react';
import type {Scope} from './types';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function isAbort(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return 'Tu sesión ha caducado. Vuelve a entrar para continuar.';
  return error instanceof Error ? error.message : 'No se ha podido completar la solicitud.';
}

export async function api<T>(path: string, options: {body?: unknown; signal?: AbortSignal; method?: string} = {}): Promise<T> {
  const hasBody = options.body !== undefined;
  const response = await fetch('/api' + path, {
    credentials: 'same-origin',
    method: options.method || (hasBody ? 'POST' : 'GET'),
    headers: hasBody ? {'Content-Type': 'application/json'} : {},
    body: hasBody ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });
  let data: unknown;
  try { data = await response.json(); }
  catch { throw new ApiError('El servidor ha devuelto una respuesta ilegible.', response.status); }
  if (!response.ok) {
    const object = data && typeof data === 'object' ? data as Record<string, unknown> : {};
    const message = object.error || object.detail;
    throw new ApiError(typeof message === 'string' ? message : `Solicitud rechazada (${response.status}).`, response.status);
  }
  return data as T;
}

export function scopeQuery(scope: Scope, extra: Record<string, string | number | undefined> = {}): string {
  const values = {...scope, ...extra};
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  });
  return '?' + params.toString();
}

/** Each request belongs to one URL + identity generation. Late responses cannot replace a new view. */
export function useRemote<T>(path: string | null, identityKey: string, refreshToken = 0, pollMs = 0) {
  const [state, setState] = useState<{data: T | null; loading: boolean; error: string; updated: Date | null}>({data: null, loading: !!path, error: '', updated: null});
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const lastResource = useRef('');
  const refresh = useCallback(() => setRevision(n => n + 1), []);
  useEffect(() => {
    const current = ++generation.current;
    const controller = new AbortController();
    let active = false;
    const resourceKey = identityKey + '|' + path;
    if (lastResource.current !== resourceKey) setState({data: null, loading: !!path, error: '', updated: null});
    lastResource.current = resourceKey;
    const load = async () => {
      if (!path || active || controller.signal.aborted) return;
      active = true;
      setState(previous => ({...previous, loading: true, error: ''}));
      try {
        const data = await api<T>(path, {signal: controller.signal});
        if (generation.current === current && !controller.signal.aborted) setState({data, loading: false, error: '', updated: new Date()});
      } catch (error) {
        if (!isAbort(error) && generation.current === current && !controller.signal.aborted) setState(previous => ({...previous, loading: false, error: errorMessage(error)}));
      } finally { active = false; }
    };
    void load();
    const timer = pollMs > 0 && path ? window.setInterval(() => { if (!document.hidden) void load(); }, pollMs) : undefined;
    return () => { controller.abort(); if (timer) window.clearInterval(timer); };
  }, [path, identityKey, refreshToken, revision, pollMs]);
  return {...state, refresh};
}
