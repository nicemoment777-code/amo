import https from 'node:https';
import {isIP} from 'node:net';

const resolved=new Map();
// Retain TLS hostname validation when the VPS system DNS is unavailable.
export async function labelDownload(url,{fetcher=fetch,request=https.get}={}){
  let address=resolved.get(url.hostname)?.until>Date.now()?resolved.get(url.hostname).address:null;
  if(!address){try{return await fetcher(url,{redirect:'error',signal:AbortSignal.timeout(30000)});}
  catch(error){
    if(!['EAI_AGAIN','ENOTFOUND'].includes(error.cause?.code))throw error;
    const dns=await fetcher('https://dns.google/resolve?name='+encodeURIComponent(url.hostname)+'&type=A',{signal:AbortSignal.timeout(15000)});
    if(!dns.ok)throw Error('Не удалось разрешить адрес источника этикетки');
    const answer=await dns.json();
    const record=answer.Status===0&&answer.Answer?.find(v=>v.type===1&&isIP(v.data)===4);
    address=record?.data;
    if(!address)throw Error('Адрес источника этикетки не найден в DNS');
    resolved.set(url.hostname,{address,until:Date.now()+Math.min(Math.max(record.TTL||60,1),300)*1000});
  }}
    return await new Promise((resolve,reject)=>{
      const req=request(url,{agent:false,signal:AbortSignal.timeout(30000),lookup:(host,options,done)=>done(null,options.all?[{address,family:4}]:address,4)},response=>{
        const stream=new ReadableStream({start(controller){response.on('data',chunk=>controller.enqueue(chunk));response.on('end',()=>controller.close());response.on('error',error=>controller.error(error));},cancel(){response.destroy();}});
        resolve(new Response(stream,{status:response.statusCode,headers:response.headers}));
      });req.on('error',reject);
    });
}

