export class DevFlight {
  constructor({endpoint='http://127.0.0.1:8787', token='', context={}, developer_id, session_id,
               origin_user_name, eventsPath, attempts=3, timeoutMs=10000}={}) {
    this.endpoint=endpoint; this.token=token; this.context=context;
    this.developer_id=developer_id; this.session_id=session_id;
    this.origin_user_name=origin_user_name;
    const url=new URL(endpoint);
    this.eventsUrl=url.pathname!=='/' && url.pathname!=='' ? url.href :
      new URL(eventsPath || (url.port==='8788'?'/api/events':'/events'),url).href;
    if(!Number.isInteger(attempts) || attempts<1 || attempts>5) throw new Error('attempts must be 1..5');
    if(!Number.isFinite(timeoutMs) || timeoutMs<100 || timeoutMs>60000) throw new Error('timeoutMs must be 100..60000');
    this.attempts=attempts; this.timeoutMs=timeoutMs;
  }

  // Persist the prepared object yourself before send() when offline durability
  // is required. HTTP retries keep an identical ID/body; they are not a disk queue.
  async prepare(event_type, data, agent='javascript', options={}) {
    const crypto=globalThis.crypto || await import('node:crypto');
    const event_id=options.event_id || crypto.randomUUID();
    if(typeof event_id!=='string' || !event_id || event_id.length>512) throw new Error('Invalid event_id');
    const event={schema_version:2,event_id,timestamp:options.timestamp || new Date().toISOString(),
      event_type,data,agent,context:{...this.context},developer_id:this.developer_id,
      session_id:this.session_id,origin_user_name:this.origin_user_name};
    for(const name of ['model','provider','project_id','request_id','origin_user_id','origin_user_name',
                       'session_id','activity_kind','status','usage_kind']) {
      if(options[name]!==undefined) event[name]=options[name];
    }
    return event;
  }

  async send(event) {
    if(!event || typeof event.event_id!=='string' || !event.event_id) throw new Error('Use prepare() or supply a stable event_id');
    const body=JSON.stringify(event);
    let failure;
    for(let attempt=0;attempt<this.attempts;attempt++) {
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),this.timeoutMs);
      let delay=Math.min(1000*2**attempt,5000),retry=true;
      try {
        const response=await fetch(this.eventsUrl,{
          method:'POST',headers:{'Content-Type':'application/json',...(this.token?{Authorization:`Bearer ${this.token}`}:{})},
          body,signal:controller.signal
        });
        if(response.ok) return await response.json();
        retry=[408,429,500,502,503,504].includes(response.status);
        const after=response.headers.get('Retry-After');
        if(after) {
          const seconds=Number(after);
          const requested=Number.isFinite(seconds)?seconds*1000:Date.parse(after)-Date.now();
          if(Number.isFinite(requested)) delay=Math.max(0,Math.min(requested,30000));
        }
        failure=new Error(`DevFlight HTTP ${response.status}`);
        failure.status=response.status;
      } catch(error) {
        failure=error;
      } finally {
        clearTimeout(timer);
      }
      failure.eventId=event.event_id;
      if(!retry || attempt+1===this.attempts) throw failure;
      await new Promise(resolve=>setTimeout(resolve,delay));
    }
    throw failure;
  }

  async emit(event_type, data, agent='javascript', options={}) {
    return this.send(await this.prepare(event_type,data,agent,options));
  }
}
