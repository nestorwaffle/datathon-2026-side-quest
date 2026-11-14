export class DevFlight {
  constructor({endpoint='http://127.0.0.1:8787', token='', context={}, developer_id, session_id}={}) {
    this.endpoint=endpoint; this.token=token; this.context=context;
    this.developer_id=developer_id; this.session_id=session_id;
  }
  async emit(event_type, data, agent='javascript') {
    const response=await fetch(`${this.endpoint}/events`, {
      method:'POST', headers:{'Content-Type':'application/json', ...(this.token?{Authorization:`Bearer ${this.token}`}:{})},
      body:JSON.stringify({event_type,data,agent,context:this.context,developer_id:this.developer_id,session_id:this.session_id})
    });
    if(!response.ok) throw new Error(`DevFlight HTTP ${response.status}`);
    return response.json();
  }
}
