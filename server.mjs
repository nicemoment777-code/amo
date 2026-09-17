import http from 'node:http';
import {readFile,writeFile,mkdir,rename} from 'node:fs/promises';
import {CdekClient,parseNumbers} from './cdek.mjs';
import {createSync} from './sync-service.mjs';
import {validWebhookKey,webhookOrder} from './webhook.mjs';
const port=Number(process.env.PORT||3080);
const client=new CdekClient(process.env.CDEK_CLIENT_ID||process.env.AMO_ACCOUNT_ID,process.env.CDEK_CLIENT_SECRET||process.env.AMO_PASSWORD);
await mkdir(new URL('./data/',import.meta.url),{recursive:true});
const sync=await createSync(client,new URL('./data/',import.meta.url),process.env.SYNC_INTERVAL_MINUTES);
const files={'/':['index.html','text/html'],'/app.js':['app.js','text/javascript'],'/colors.js':['colors.js','text/javascript'],'/style.css':['style.css','text/css']};
const server=http.createServer(async(req,res)=>{
  const json=(status,value)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(value));};
  res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'");
  try{
    const path=new URL(req.url,'http://localhost').pathname;
    if(path.startsWith('/webhooks/cdek/')){
      if(req.method!=='POST')return json(405,{error:'Требуется POST'});
      if(!validWebhookKey(path.slice('/webhooks/cdek/'.length),process.env.CDEK_WEBHOOK_SECRET))return json(404,{error:'Не найдено'});
      let text='';for await(const chunk of req){text+=chunk;if(text.length>65536)return json(413,{error:'Слишком большой запрос'})}
      const number=webhookOrder(JSON.parse(text));
      if(sync.state().pendingCount>=10000)return json(503,{error:'Очередь заполнена'});
      sync.enqueue([number],true);return json(200,{ok:true});
    }
    if(![`127.0.0.1:${port}`,`localhost:${port}`].includes(req.headers.host))return json(403,{error:'Недопустимый адрес'});
    if(req.headers.origin && ![`http://127.0.0.1:${port}`,`http://localhost:${port}`].includes(req.headers.origin))return json(403,{error:'Недопустимый источник'});
    if(req.method==='GET' && path==='/api/state')return json(200,sync.state());
    if(req.method==='POST' && path.startsWith('/api/')){
      if(req.headers['content-type']!=='application/json')return json(415,{error:'Требуется JSON'});
      let text='';for await(const chunk of req){text+=chunk;if(text.length>2e6)return json(413,{error:'Слишком большой запрос'});}
      const body=JSON.parse(text||'{}');
      if(path==='/api/connect'){await sync.verify();return json(200,{ok:true});}
      if(path==='/api/sync'){
        if(sync.state().job.running)return json(409,{error:'Загрузка уже выполняется'});
        const numbers=body.all?Object.keys(sync.orders):parseNumbers(body.numbers||'');
        if(!numbers.length)return json(400,{error:'Сначала добавьте номера накладных'});
        await sync.verify();sync.enqueue(numbers);return json(202,{ok:true});
      }
    }
    if(req.method==='GET' && files[path]){const [name,type]=files[path];res.writeHead(200,{'Content-Type':type+'; charset=utf-8'});return res.end(await readFile(new URL('./public/'+name,import.meta.url)));}
    json(404,{error:'Не найдено'});
  }catch(e){json(400,{error:e.name==='TimeoutError'?'СДЭК не ответил за 30 секунд':e.message});}
});
server.listen(port,'127.0.0.1',()=>{console.log(`CDEK dashboard: http://127.0.0.1:${port}`);sync.start()});
