import {readFile, writeFile, rename, chmod} from 'node:fs/promises';
import {randomBytes} from 'node:crypto';

// Device keys never enter browser responses. Snapshots are private, transient data.
export async function createBrowserControl(file, {now = Date.now} = {}) {
  let commands = {};
  try { commands = JSON.parse(await readFile(file, 'utf8')); await chmod(file,0o600); }
  catch (e) { if (e.code !== 'ENOENT') throw new Error('Не удалось прочитать очередь браузерной панели'); }
  const devices = new Map(); let tail = Promise.resolve();
  const serial = fn => { const result = tail.then(fn); tail = result.catch(() => {}); return result; };
  async function save(next) {
    const entries=Object.entries(next).sort((a,b)=>b[1].at-a[1].at);
    next=Object.fromEntries(entries.slice(0,200));
    const temp=new URL(file.toString()+'.tmp');
    await writeFile(temp,JSON.stringify(next),{mode:0o600});await chmod(temp,0o600);await rename(temp,file);
    commands=next; // Memory changes only after durable replacement.
  }
  const actions = new Set(['refresh','articles','printers','settings','auto','startup','archive','openArchive','plan','print']);
  function device(id) {
    const value=devices.get(id);
    if (!value || now()-value.at>60000) throw new Error('Компьютер не на связи. Откройте обновлённую программу Windows.');
    return value;
  }
  return {
    list: () => [...devices].map(([id,d])=>({id,name:d.name,online:now()-d.at<=60000,at:d.at})),
    snapshot: id => device(id).snapshot,
    publish(owner, body) {
      if (!body.snapshot || typeof body.snapshot!=='object' || Array.isArray(body.snapshot)) throw new Error('Некорректное состояние компьютера');
      devices.set(owner,{name:String(body.name||'Компьютер печати').slice(0,80),at:now(),snapshot:body.snapshot});
      return {ok:true};
    },
    enqueue: body => serial(async()=>{
      device(body.device);
      if (!actions.has(body.action) || !body.args || typeof body.args!=='object' || Array.isArray(body.args)) throw new Error('Некорректное действие');
      if (!/^[a-zA-Z0-9_-]{16,80}$/.test(body.requestId||'')) throw new Error('Некорректный запрос');
      const existing=Object.entries(commands).find(([,v])=>v.requestId===body.requestId);
      if (existing) {
        if(existing[1].device!==body.device || existing[1].action!==body.action) throw new Error('Идентификатор запроса уже использован');
        return {id:existing[0]};
      }
      if (Object.values(commands).some(v=>v.device===body.device && (v.status==='queued'||v.status==='running') && now()-v.at<1800000)) throw new Error('На компьютере уже выполняется действие. Дождитесь результата.');
      const id=randomBytes(20).toString('hex');
      const at=now(),args=body.action==='auto'&&body.args.enabled===true?{...body.args,enabledFrom:Math.ceil(at/1000)}:body.args;
      await save({...commands,[id]:{device:body.device,action:body.action,args,requestId:body.requestId,at,status:'queued'}}); return {id};
    }),
    take: owner => serial(async()=>{
      for (const [id,v] of Object.entries(commands)) {
        if (v.device!==owner || v.status!=='queued') continue;
        if (now()-v.at>120000) { await save({...commands,[id]:{...v,status:'expired'}}); continue; }
        // Persist BEFORE delivery. Ambiguous delivery is never repeated.
        await save({...commands,[id]:{...v,status:'running'}}); return {command:{id,action:v.action,args:v.args}};
      }
      return {command:null};
    }),
    finish: (owner,body) => serial(async()=>{
      const v=commands[body.id];
      if(v&&v.device===owner&&v.status===(body.ok===true?'done':'failed')&&JSON.stringify(v.result)===JSON.stringify(body.result))return {ok:true};
      if (!v || v.device!==owner || v.status!=='running') throw new Error('Действие недоступно');
      const next={...v,status:body.ok===true?'done':'failed',result:body.result,finishedAt:now()};
      delete next.args; await save({...commands,[body.id]:next}); return {ok:true};
    }),
    result(id) {
      const v=commands[id]; if (!v) throw new Error('Действие не найдено');
      return {status:v.status,result:v.result,at:v.at};
    }
  };
}
