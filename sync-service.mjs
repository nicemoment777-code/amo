import {readFile,writeFile,rename} from 'node:fs/promises';
import {writeFileSync,renameSync} from 'node:fs';
export async function createSync(client,directory,intervalMinutes=15){
 const file=n=>new URL(n,directory);
 const read=async(n,fallback)=>{try{return JSON.parse(await readFile(file(n),'utf8'))}catch(e){if(e.code==='ENOENT')return fallback;throw e}};
 const orders=await read('orders.json',{}),pending=new Set(await read('queue.json',[]));
 let connection=await read('sync.json',{verifiedAt:null,error:null,lastWebhookAt:null,lastSyncAt:null});
 let job={running:false,total:0,done:0,errors:[],startedAt:null,finishedAt:null};
 const interval=Math.max(1,Number(intervalMinutes)||15)*60000;let nextSyncAt=new Date(Date.now()+interval).toISOString();
 const saveQueue=()=>{writeFileSync(file('queue.tmp'),JSON.stringify([...pending]));renameSync(file('queue.tmp'),file('queue.json'))};
 const saveMeta=()=>writeFileSync(file('sync.json'),JSON.stringify(connection,null,2));
 async function verify(){try{await client.token();connection.verifiedAt=new Date().toISOString();connection.error=null;saveMeta()}catch(e){connection.error=e.message;saveMeta();throw e}}
 async function drain(){
  if(job.running||!pending.size)return;
  job={running:true,total:pending.size,done:0,errors:[],startedAt:new Date().toISOString(),finishedAt:null};
  try{
   await verify();
   for(const n of [...pending]){
    try{
     const raw=await client.order(n),old=orders[n];
     orders[n]={number:n,raw,source:'cdek-api',syncedAt:new Date().toISOString(),...(old?.source==='cdek-cabinet'?{cabinetSnapshot:old}:old?.cabinetSnapshot?{cabinetSnapshot:old.cabinetSnapshot}:{})};
     try{await writeFile(file('orders.tmp'),JSON.stringify(orders,null,2));await rename(file('orders.tmp'),file('orders.json'))}catch(e){if(old)orders[n]=old;else delete orders[n];throw e}
     pending.delete(n);saveQueue();
    }catch(e){job.errors.push({number:n,message:e.message})}
    job.done++;await new Promise(r=>setTimeout(r,300));
   }
   connection.lastSyncAt=new Date().toISOString();saveMeta();
  }catch(e){job.errors.push({number:'Авторизация',message:e.message})}
  finally{job.running=false;job.finishedAt=new Date().toISOString()}
 }
 function enqueue(numbers,webhook=false){for(const n of numbers)pending.add(n);saveQueue();if(webhook){connection.lastWebhookAt=new Date().toISOString();saveMeta()}void drain()}
 function start(){if(client.id&&client.secret)enqueue(Object.keys(orders));setInterval(()=>{nextSyncAt=new Date(Date.now()+interval).toISOString();if(client.id&&client.secret)enqueue(Object.keys(orders))},interval).unref();setInterval(()=>{if(client.id&&client.secret)void drain()},60000).unref()}
 return {orders,verify,enqueue,start,state:()=>({configured:!!(client.id&&client.secret),connection,autoSyncMinutes:interval/60000,nextSyncAt,pendingCount:pending.size,orders:Object.values(orders),job})};
}
