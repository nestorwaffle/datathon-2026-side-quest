import {useState} from 'react';
import {Database, Plus, ShieldCheck, Trash2} from 'lucide-react';
import type {Identity, SourceInfo} from './lib/types';
import {api, errorMessage} from './lib/api';
import {Badge, DataTable, Notice, Panel} from './ui';

export default function SourceAccess({source, me, onChange}: {source: SourceInfo | null; me: Identity; onChange: () => void}) {
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  if (!source?.can_manage_source) return null;
  const grants = source.grants || [];
  const available = (me.organizations || []).filter(org => !grants.some(grant => grant.org_id === org.id));
  const grant = async (orgId: string, enabled: boolean) => {
    if (busy) return;
    setBusy(true); setError(''); setMessage('');
    try {
      await api('/source/grants', {body: {org_id: orgId, enabled}});
      setMessage(enabled ? 'Organización autorizada para consultar el espacio compartido.' : 'Acceso compartido revocado. La organización conserva sus datos propios.'); setTarget(''); onChange();
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  };
  return <Panel title="Quién puede leer el espacio compartido" description="El propietario local decide qué organizaciones de acceso pueden consultar esta fuente RawTree completa." actions={<Badge><ShieldCheck size={12}/>Propietario de la fuente</Badge>}>
    <div className="panel-inset"><Notice><Database size={14}/>Una autorización permite a los miembros de esa organización leer los datos del espacio compartido, incluidos eventos de otros emisores. No cambia las credenciales del modelo ni de RawTree.</Notice>{(error || message) && <Notice tone={error ? 'error' : 'success'}>{error || message}</Notice>}</div>
    <DataTable rows={grants.map(item => ({...item}))} columns={[{key: 'name', title: 'Organización'}, {key: 'owner', title: 'Acceso', render: row => <Badge tone="success">{row.owner ? 'Propietario' : 'Lectura compartida'}</Badge>}, {key: 'action', title: 'Acción', render: row => <button className="text-button danger" disabled={busy || !!row.owner} onClick={() => { if (window.confirm('¿Revocar el acceso de esta organización a la fuente compartida?')) void grant(String(row.org_id), false); }}><Trash2 size={13}/>Revocar acceso</button>}]}/>
    {available.length > 0 && <form className="source-grant-form" onSubmit={event => { event.preventDefault(); if (target) void grant(target, true); }}><label>Autorizar organización<select value={target} onChange={event => setTarget(event.target.value)}><option value="">Selecciona una organización</option>{available.map(org => <option key={org.id} value={org.id}>{org.name}</option>)}</select></label><button className="button" disabled={busy || !target}><Plus size={14}/>{busy ? 'Guardando…' : 'Autorizar lectura compartida'}</button></form>}
  </Panel>;
}
