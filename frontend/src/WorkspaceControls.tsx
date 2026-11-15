import {useRef, useState} from 'react';
import {Archive, Check, Copy, KeyRound, Plus, ShieldCheck, Trash2, Users} from 'lucide-react';
import type {Identity, Row} from './lib/types';
import {api, errorMessage} from './lib/api';
import {text} from './lib/format';
import {Badge, DataTable, Notice, Panel, Spinner} from './ui';

export interface SettingsData {users?: Row[]; teams?: Row[]; projects?: Row[]; credentials?: Row[]; integrations?: Row; organizations?: {id: string; name: string}[]; mode?: string;}
const roles = [{id: 'admin', label: 'Administrador'}, {id: 'team_manager', label: 'Responsable de equipo'}, {id: 'member', label: 'Miembro'}, {id: 'viewer', label: 'Lector'}];
const operations = [{id: 'ingest_key', label: 'Credencial de ingesta'}, {id: 'user', label: 'Usuario'}, {id: 'team', label: 'Equipo'}, {id: 'project', label: 'Proyecto'}, {id: 'organization', label: 'Organización de acceso'}];

export default function WorkspaceControls({me, data, onChange}: {me: Identity; data: SettingsData; onChange: () => void}) {
  const [kind, setKind] = useState('ingest_key');
  const [name, setName] = useState('');
  const [role, setRole] = useState('member');
  const [team, setTeam] = useState('');
  const [owner, setOwner] = useState('');
  const [credential, setCredential] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [legacyTable, setLegacyTable] = useState('dev_events_raw');
  const [legacyTrace, setLegacyTrace] = useState('');
  const lock = useRef(false);
  const post = async (body: Row) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(''); setMessage(''); setCredential('');
    try {
      const result = await api<Row>('/settings', {body});
      if (typeof result.credential === 'string') { setCredential(result.credential); setCopied(false); }
      setMessage(result.revoked ? 'Credencial revocada.' : 'Cambios guardados.'); onChange();
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); lock.current = false; }
  };
  const copy = async () => { try { await navigator.clipboard.writeText(credential); setCopied(true); } catch { setError('No se ha podido copiar. Selecciona el valor y cópialo manualmente.'); } };
  const assignLegacy = async () => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(''); setMessage('');
    try {
      await api('/explorer/assign', {body: {table: legacyTable, trace_id: legacyTrace}});
      setMessage('La traza histórica exacta queda asignada a la organización actual.'); onChange();
    } catch (failure) { setError(errorMessage(failure)); }
    finally { lock.current = false; setBusy(false); }
  };

  if (me.role !== 'admin') return <Notice><ShieldCheck size={14}/>La administración de accesos y credenciales requiere un administrador. Tu alcance de lectura se muestra en la cabecera de la fuente.</Notice>;
  return <><Panel title="Accesos y emisores" description="La cuenta de acceso controla los permisos. La actividad analítica pertenece al espacio RawTree autorizado." actions={<Badge><ShieldCheck size={12}/>Administración</Badge>}>
    <form className="management-form" onSubmit={event => { event.preventDefault(); void post({kind, name, role, team_id: team || null, user_id: owner || undefined}); }}><label>Crear<select value={kind} onChange={event => { setKind(event.target.value); setCredential(''); setMessage(''); }}>{operations.map(operation => <option key={operation.id} value={operation.id}>{operation.label}</option>)}</select></label>{kind === 'ingest_key' ? <label>Identidad del emisor<select value={owner} onChange={event => setOwner(event.target.value)}><option value="">Administrador actual</option>{data.users?.filter(user => user.role !== 'viewer').map(user => <option key={text(user.id)} value={text(user.id)}>{text(user.name)} · {text(user.role)}</option>)}</select></label> : <label>Nombre<input value={name} onChange={event => setName(event.target.value)} placeholder="Nombre identificable" maxLength={120} required/></label>}{kind === 'user' && <><label>Rol<select value={role} onChange={event => setRole(event.target.value)}>{roles.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label><label>Equipo<select value={team} onChange={event => setTeam(event.target.value)}><option value="">Sin equipo</option>{data.teams?.map(item => <option key={text(item.id)} value={text(item.id)}>{text(item.name)}</option>)}</select></label></>}<button className="primary" disabled={busy || (kind !== 'ingest_key' && !name.trim())}>{busy ? <Spinner label="Guardando…"/> : <><Plus size={14}/>Crear</>}</button></form>
    {(error || message) && <div className="panel-inset"><Notice tone={error ? 'error' : 'success'}>{error || message}</Notice></div>}
    {credential && <div className="credential-result"><div><KeyRound size={17}/><strong>Guarda esta credencial ahora</strong><button className="button" onClick={() => void copy()}>{copied ? <Check size={13}/> : <Copy size={13}/>} {copied ? 'Copiada' : 'Copiar'}</button></div><p>Solo se muestra en esta respuesta. Úsala en la integración local del emisor correspondiente.</p><textarea readOnly aria-label="Nueva credencial personal" value={credential} onFocus={event => event.target.select()}/></div>}
  </Panel>
  <Panel title="Miembros y permisos" description="Los cambios se aplican también a sesiones y credenciales existentes."><DataTable rows={data.users || []} columns={[{key: 'name', title: 'Miembro', render: user => <div className="entity"><div className="avatar">{text(user.name).slice(0, 1).toUpperCase()}</div><div><strong>{text(user.name)}</strong><small>{text(user.id)}</small></div></div>}, {key: 'role', title: 'Rol', render: user => <select aria-label={`Rol de ${text(user.name)}`} value={text(user.role)} disabled={busy} onChange={event => void post({kind: 'membership', user_id: user.id, role: event.target.value, team_id: user.team_id})}>{roles.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select>}, {key: 'team_id', title: 'Equipo', render: user => <select aria-label={`Equipo de ${text(user.name)}`} value={text(user.team_id, '')} disabled={busy} onChange={event => void post({kind: 'membership', user_id: user.id, role: user.role, team_id: event.target.value || null})}><option value="">Sin equipo</option>{data.teams?.map(item => <option key={text(item.id)} value={text(item.id)}>{text(item.name)}</option>)}</select>}]}/></Panel>
  <div className="two-columns">{(['teams', 'projects'] as const).map(key => <Panel key={key} title={key === 'teams' ? 'Equipos' : 'Proyectos'} actions={<Users size={16}/>}><DataTable rows={data[key] || []} columns={[{key: 'name', title: 'Nombre'}, {key: 'id', title: 'Identificador', className: 'mono'}]} empty={key === 'teams' ? 'No hay equipos creados' : 'No hay proyectos creados'}/></Panel>)}</div>
  <Panel title="Credenciales emitidas" description="Puedes revocar cada credencial de forma independiente."><DataTable rows={data.credentials || []} columns={[{key: 'purpose', title: 'Uso', render: row => row.purpose === 'ingest' ? 'Envío de telemetría' : text(row.purpose)}, {key: 'user_id', title: 'Propietario', render: row => text(data.users?.find(user => user.id === row.user_id)?.name || row.user_id)}, {key: 'revoked', title: 'Estado', render: row => <Badge tone={row.revoked ? 'neutral' : 'success'}>{row.revoked ? 'Revocada' : 'Activa'}</Badge>}, {key: 'action', title: 'Acción', render: row => <button className="text-button danger" disabled={busy || !!row.revoked} onClick={() => { if (window.confirm('¿Revocar esta credencial? El emisor dejará de poder autenticarse con ella.')) void post({kind: 'revoke_key', credential_id: row.id}); }}><Trash2 size={13}/>Revocar</button>}]} empty="No hay credenciales disponibles"/></Panel>
  <Panel title="Archivo local" description="Archiva los payloads confirmados; la cola pendiente se conserva."><div className="retention-controls"><Archive size={20}/><p>Los archivos mantienen los registros completos. El archivado reduce la base activa, pero no elimina los datos ni amplía el límite de disco.</p><button className="button" disabled={busy} onClick={() => void post({kind: 'retention', archive_after_days: 7})}>Archivar tras 7 días</button><button className="button" disabled={busy} onClick={() => void post({kind: 'retention', archive_after_days: 0})}>Desactivar archivo</button></div></Panel>
  <details className="details-json"><summary>Compatibilidad con históricos aislados<ShieldCheck size={14}/></summary><p className="legacy-help">El espacio compartido no necesita esta asignación. Para organizaciones aisladas, el propietario local puede autorizar una traza histórica exacta.</p><form className="management-form legacy-form" onSubmit={event => { event.preventDefault(); void assignLegacy(); }}><label>Tabla<select value={legacyTable} onChange={event => setLegacyTable(event.target.value)}>{['dev_logs', 'dev_traces', 'dev_metrics', 'dev_events_raw', 'dev_artifacts_raw'].map(table => <option key={table}>{table}</option>)}</select></label><label>ID de traza exacto<input value={legacyTrace} onChange={event => setLegacyTrace(event.target.value)} placeholder="32 caracteres hexadecimales" maxLength={32}/></label><button className="button" disabled={busy || !/^[a-fA-F0-9]{32}$/.test(legacyTrace)}>Autorizar esta traza</button></form></details></>;
}
