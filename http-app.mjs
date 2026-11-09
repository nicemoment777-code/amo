import http from 'node:http';
import {labelDownload} from './label-download.mjs';
import {browserPdf} from './browser-pdf.mjs';
import {randomBytes} from 'node:crypto';
import {webCatalog} from './web-catalog.mjs';
import {readFile} from 'node:fs/promises';
import {parseNumbers} from './cdek.mjs';
import {validWebhookKey, webhookOrder} from './webhook.mjs';
import {callbackPath} from './amocrm.mjs';
import {createHash, timingSafeEqual} from 'node:crypto';

const files = {'/': ['index.html', 'text/html'], '/app.js': ['app.js', 'text/javascript'], '/colors.js': ['colors.js', 'text/javascript'], '/style.css': ['style.css', 'text/css'], '/login': ['login.html', 'text/html'], '/login.js': ['login.js', 'text/javascript'], '/login.css': ['login.css', 'text/css']};
const publicPaths = new Set(['/login', '/login.js', '/login.css']);
async function readJson(req, limit) {
  if (req.headers['content-type']?.split(';')[0].trim() !== 'application/json') throw Object.assign(new Error('Требуется JSON'), {status: 415});
  let size = 0; const chunks = [];
  for await (const chunk of req) { size += chunk.length; if (size > limit) throw Object.assign(new Error('Слишком большой запрос'), {status: 413}); chunks.push(chunk); }
  try { const value = JSON.parse(Buffer.concat(chunks).toString() || '{}'); if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(); return value; }
  catch { throw new Error('Некорректный JSON'); }
}

export function createApp({sync, auth, webhookSecret, amocrm, printAgentHash = '', labelHosts = [], printDevices, browserControl, installerFile=new URL('./data/private/SnowbrickSetup.exe',import.meta.url)}) {
  const catalogs=new Map(),browserBatches=new Map();let preparingBrowser=false;
  const server = http.createServer(async (req, res) => {
    const json = (status, value) => { res.writeHead(status, {'Content-Type': 'application/json; charset=utf-8'}); res.end(JSON.stringify(value)); };
    const redirect = path => { res.writeHead(302, {Location: path}); res.end(); };
    res.setHeader('Cache-Control', 'no-store'); res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
    try {
      const path = new URL(req.url, 'http://localhost').pathname;
      async function sendLabel(id,prepare=false) {
          const result = await amocrm.printLabel(id);
          if (!result.url) return json(409,{error:'В заявке нет ссылки на PDF этикетки. Заполните поле этикетки в amoCRM и обновите карточки.'});
          const url = new URL(result.url);
          if (url.protocol !== 'https:' || url.port || url.username || url.password || !labelHosts.includes(url.hostname)) return json(400, {error: 'Домен этикетки ещё не разрешён для печати'});
          const response = await labelDownload(url);
          if(response.status===404)return json(409,{error:'Файл этикетки по ссылке amoCRM не найден (404). Обновите этикетку в amoCRM и повторите подготовку PDF.'});
          if (!response.ok) return json(502, {error: 'Хранилище этикеток вернуло ошибку '+response.status+'. Попробуйте позже или обновите ссылку в amoCRM.'});
          const reader = response.body.getReader(); const chunks = []; let length = 0;
          try { while (true) { const {done, value} = await reader.read(); if (done) break; length += value.length; if (length > 10e6) throw new Error('Слишком большой файл этикетки'); chunks.push(value); } }
          finally { await reader.cancel(); }
          const content = Buffer.concat(chunks);
          if (!content.subarray(0, 5).equals(Buffer.from('%PDF-'))) return json(415, {error: 'Этикетка должна быть PDF'});
          if(prepare)return {item:result.item,content};
          res.writeHead(200, {'Content-Type': 'application/pdf','Content-Disposition':'attachment; filename="label-'+id+'.pdf"'}); return res.end(content);
      }
      if (path.startsWith('/webhooks/cdek/')) {
        if (req.method !== 'POST') return json(405, {error: 'Требуется POST'});
        if (!validWebhookKey(path.slice('/webhooks/cdek/'.length), webhookSecret)) return json(404, {error: 'Не найдено'});
        const number = webhookOrder(await readJson(req, 65536));
        if (sync.state().pendingCount >= 10000) return json(503, {error: 'Очередь заполнена'});
        sync.enqueue([number], true); return json(200, {ok: true});
      }
      const port = server.address().port;
      const localOrigins = [`http://127.0.0.1:${port}`, `http://localhost:${port}`];
      if (![`127.0.0.1:${port}`, `localhost:${port}`].includes(req.headers.host)) return json(403, {error: 'Недопустимый адрес'});
      if (req.method === 'GET' && path === '/healthz') return json(200, {ok: true});
      if (path === '/api/print-pair/start' || path === '/api/print-pair/poll') {
        if (!auth.enabled || !printDevices) return json(404, {error: 'Не настроено подключение устройств'});
        if (req.method !== 'POST') return json(405, {error: 'Требуется POST'});
        const body = await readJson(req, 2048);
        return json(200, path.endsWith('/start') ? printDevices.begin(body, req.headers['x-real-ip'] || req.socket.remoteAddress) : printDevices.poll(body));
      }
      if (path.startsWith('/api/print-agent/')) {
        const bearer = req.headers.authorization?.match(/^Bearer ([A-Za-z0-9_-]{43})$/)?.[1];
        const legacy = bearer && /^[a-f0-9]{64}$/.test(printAgentHash) && timingSafeEqual(createHash('sha256').update(bearer).digest(), Buffer.from(printAgentHash, 'hex'));
        const owner = legacy ? 'legacy' : printDevices?.authorize(bearer);
        if (!auth.enabled || !amocrm || !owner) return json(401, {error: 'Нет доступа к печати'});
        if (browserControl && path.startsWith('/api/print-agent/browser/')) {
          const client=req.headers['x-print-client'];
          if(!/^[a-f0-9]{32}$/.test(client||''))return json(409,{error:'Обновите модуль печати Windows'});
          const browserOwner=owner+':'+client;

          if (req.method==='GET' && path.endsWith('/poll')) return json(200,await browserControl.take(browserOwner));
          if (req.method==='POST' && path.endsWith('/snapshot')) return json(200,browserControl.publish(browserOwner,await readJson(req,8e6)));
          if (req.method==='POST' && path.endsWith('/result')) return json(200,await browserControl.finish(browserOwner,await readJson(req,100000)));
          return json(405,{error:'Недопустимое действие'});
        }
        if (printDevices && req.method==='POST' && path==='/api/print-agent/mark-printed') {
          return json(200,await printDevices.markOwnerPrinted((await readJson(req,1024)).id));
        }
        if (printDevices && path==='/api/print-agent/history') {
          if (req.method==='GET') return json(200,printDevices.history());
          if (req.method==='POST') return json(200,await printDevices.record((await readJson(req,100000)).entries,owner));
          return json(405,{error:'Недопустимое действие'});
        }
        if (printDevices && req.method === 'POST' && ['/api/print-agent/claim', '/api/print-agent/complete'].includes(path)) {
          const body = await readJson(req, 1024);
          return json(200, path.endsWith('/claim') ? await printDevices.claim(body.id, owner) : await printDevices.complete(body.id, owner));
        }
        if (req.method !== 'GET') return json(405, {error: 'Требуется GET'});
        const params = new URL(req.url, 'http://localhost').searchParams;
        if (path === '/api/print-agent/leads') {
          const from = Number(params.get('from'));
          if (!Number.isSafeInteger(from) || from < 0) return json(400, {error: 'Некорректная дата'});
          const data=await amocrm.printCandidates(from, params.get('sample') === '1');
          await printDevices?.markShipped?.(data.items);
          return json(200,data);
        }
        const itemId = path.match(/^\/api\/print-agent\/item\/(\d+)$/)?.[1];
        if (itemId) return json(200, (await amocrm.printLabel(itemId)).item);
        const labelId = path.match(/^\/api\/print-agent\/label\/(\d+)$/)?.[1];
        if (labelId) {
          return sendLabel(labelId);
        }
        return json(404, {error: 'Не найдено'});
      }
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        const allowed = auth.enabled ? [auth.origin] : localOrigins;
        if ((auth.enabled || req.headers.origin) && !allowed.includes(req.headers.origin)) return json(403, {error: 'Недопустимый источник запроса'});
      }
      if (req.method === 'POST' && path === '/api/auth/login') {
        if (!auth.enabled) return json(404, {error: 'Вход не настроен'});
        const result = await auth.login(req, await readJson(req, 4096));
        if (result.cookie) res.setHeader('Set-Cookie', result.cookie);
        if (result.status === 429) res.setHeader('Retry-After', '900');
        return json(result.status, result.error ? {error: result.error} : {ok: true});
      }
      if (req.method === 'POST' && path === '/api/auth/logout') {
        if (auth.enabled) res.setHeader('Set-Cookie', auth.logout(req));
        return json(200, {ok: true});
      }
      const session = auth.session(req);
      if (amocrm && path === callbackPath) {
        if (req.method !== 'GET') return json(405, {error: 'Требуется GET'});
        const params = new URL(req.url, 'http://localhost').searchParams;
        if (!params.size) return json(200, {ok: true, message: 'Адрес авторизации amoCRM готов. Начните подключение на странице /integrations/amocrm после входа.'});
        if (!auth.enabled || !session) return redirect('/login');
        try { await amocrm.callback(params, req.headers.cookie); return redirect('/integrations/amocrm?result=ok'); }
        catch { return redirect('/integrations/amocrm?result=error'); }
      }
      if (req.method === 'GET' && path === '/login' && (!auth.enabled || session) && new URL(req.url,'http://localhost').searchParams.get('prefill') !== '1') return redirect('/');
      if (auth.enabled && !session && !publicPaths.has(path)) {
        if (path.startsWith('/api/')) return json(401, {error: 'Войдите в аккаунт'});
        return redirect('/login');
      }
      if(req.method==='GET'&&path==='/api/printing/installer'){
        if(!auth.enabled||!session)return json(403,{error:'Войдите на сайт для скачивания персонального установщика'});
        try{const installer=await readFile(installerFile);
          res.writeHead(200,{'Content-Type':'application/vnd.microsoft.portable-executable','Content-Disposition':'attachment; filename="SnowbrickSetup.exe"','Cache-Control':'private, no-store'});return res.end(installer);
        }catch{return json(503,{error:'Персональный установщик ещё готовится. Повторите скачивание позже.'});}
      }
      if(req.method==='GET'&&path==='/api/printing/report-items'&&amocrm){
        if(!auth.enabled||!session)return json(403,{error:'Войдите на сайт'});
        const query=new URL(req.url,'http://localhost').searchParams;
        const from=Number(query.get('from')),to=Number(query.get('to'));
        const scope=query.get('pipeline')||'8604134',pipelineId=scope==='all'?null:Number(scope);
        if(!query.has('from')||!query.has('to')||!Number.isSafeInteger(from)||!Number.isSafeInteger(to)||from<0||to<from||to-from>366*86400||
            (pipelineId!==null&&(!Number.isSafeInteger(pipelineId)||pipelineId<=0)))return json(400,{error:'Некорректный период или воронка'});
        return json(200,await amocrm.reportItems(from,to,pipelineId));
      }
      if(req.method==='POST'&&path==='/api/printing/mark-printed'&&printDevices){
        if(!auth.enabled||!session)return json(403,{error:'Войдите на сайт'});
        return json(200,await printDevices.markOwnerPrinted((await readJson(req,1024)).id));
      }
      if(req.method==='POST'&&path==='/api/printing/recover'&&printDevices){
        if(!auth.enabled||!session)return json(403,{error:'Войдите на сайт'});
        return json(200,await printDevices.recoverForManualRetry(await readJson(req,2048)));
      }
      if (req.method==='GET' && path==='/api/printing/history' && printDevices) {
        if (!auth.enabled || !session) return json(403,{error:'Войдите на сайт'});
        return json(200,printDevices.history());
      }
      if (req.method === 'GET' && path === '/api/auth/session') return json(200, {enabled: auth.enabled, username: session?.username});
      if (browserControl && path.startsWith('/api/browser/')) {
        if (!auth.enabled || !session) return json(403,{error:'Войдите на сайт'});
        const browserLabel=path.match(/^\/api\/browser\/label\/(\d+)$/)?.[1];
        if(req.method==='GET'&&browserLabel)return sendLabel(browserLabel);
        if(req.method==='POST'&&path==='/api/browser/prepare-pdf'){
          if(preparingBrowser)return json(409,{error:'Подготовка PDF уже выполняется. Подождите.'});
          const body=await readJson(req,10000);
          if(!Array.isArray(body.ids)||!body.ids.length||body.ids.length>100||body.ids.some(v=>!/^\d{1,20}$/.test(String(v))))return json(400,{error:'Выберите от 1 до 100 заявок'});
          preparingBrowser=true;
          try{
            const items=[],contents=[];let totalBytes=0;
            for(const id of new Set(body.ids.map(String))){const result=await sendLabel(id,true);if(!result)return;totalBytes+=result.content.length;if(totalBytes>100e6)throw Error('Слишком большая партия PDF. Выберите меньше заявок.');items.push(result.item);contents.push(result.content);}
            const pdf=await browserPdf(items,contents),token=randomBytes(24).toString('hex');
            for(const [key,batch] of browserBatches)if(batch.expires<Date.now())browserBatches.delete(key);
            browserBatches.set(token,{ids:items.map(v=>v.id),expires:Date.now()+1800000});
            res.writeHead(200,{'Content-Type':'application/pdf','X-Print-Confirmation':token,'Content-Disposition':'inline; filename="labels.pdf"'});return res.end(pdf);
          }finally{preparingBrowser=false;}
        }
        if(req.method==='POST'&&path==='/api/browser/confirm-pdf'){
          const body=await readJson(req,1024),batch=browserBatches.get(body.token);
          if(!batch||batch.expires<Date.now())return json(409,{error:'Подтверждение истекло. Обновите историю.'});
          await printDevices.markBrowserPrinted(batch.ids);browserBatches.delete(body.token);return json(200,{ok:true});
        }
        if (req.method==='GET' && path==='/api/browser/history') return json(200,printDevices.history());
        if (req.method==='GET' && path==='/api/browser/catalog') {
          const from=Number(new URL(req.url,'http://localhost').searchParams.get('from'));
          if(!Number.isSafeInteger(from)||from<0||from>253402289999)return json(400,{error:'Некорректная дата'});
          let cached=catalogs.get(from);
          if(!cached || Date.now()-cached.at>15000) {
            if(catalogs.size>=8)catalogs.delete(catalogs.keys().next().value);
            cached={at:Date.now(),promise:amocrm.printCandidates(from)};catalogs.set(from,cached);
            cached.promise.catch(()=>catalogs.delete(from));
          }
          const data=await cached.promise;await printDevices.markShipped?.(data.items);const history=printDevices.history();
          return json(200,{items:webCatalog(data.items,history),journal:history.events,at:Date.now()});
        }
        if (req.method==='GET' && path==='/api/browser/devices') return json(200,{devices:browserControl.list()});
        if (req.method==='GET' && path==='/api/browser/snapshot') return json(200,browserControl.snapshot(new URL(req.url,'http://localhost').searchParams.get('device')));
        if (req.method==='POST' && path==='/api/browser/command') return json(200,await browserControl.enqueue(await readJson(req,100000)));
        const commandId=path.match(/^\/api\/browser\/command\/([a-f0-9]{40})$/)?.[1];
        if (req.method==='GET' && commandId) return json(200,browserControl.result(commandId));
        return json(404,{error:'Не найдено'});
      }
      if (req.method==='GET' && ['/', '/printer.js','/printer.css','/printer-model.js'].includes(path)) {
        const name={'/':'printer.html','/printer.js':'printer.js','/printer.css':'printer.css','/printer-model.js':'printer-model.js'}[path];
        const contents=await readFile(new URL('./public/'+name,import.meta.url));
        res.writeHead(200,{'Content-Type':(name.endsWith('.html')?'text/html':name.endsWith('.css')?'text/css':'text/javascript')+'; charset=utf-8'}); return res.end(contents);
      }
      if (req.method==='GET' && path==='/cdek') {
        res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'}); return res.end(await readFile(new URL('./public/index.html',import.meta.url)));
      }
      if (amocrm && (path.startsWith('/api/amocrm/') || path === '/integrations/amocrm' || path === '/amocrm.js')) {
        if (!auth.enabled || !session) return json(403, {error: 'Для подключения amoCRM требуется вход на сайт'});
        if (printDevices && req.method === 'GET' && path === '/api/amocrm/devices') return json(200, {devices: printDevices.list()});
        if (printDevices && req.method === 'POST' && path === '/api/amocrm/devices/approve') return json(200, await printDevices.approve(await readJson(req, 2048)));
        if (printDevices && req.method === 'POST' && path === '/api/amocrm/devices/revoke') return json(200, await printDevices.revoke((await readJson(req, 1024)).id));
        if (req.method === 'GET' && path === '/api/amocrm/status') return json(200, amocrm.status());
        if (req.method === 'POST' && path === '/api/amocrm/configure') { await amocrm.configure(await readJson(req, 8192)); return json(200, {ok: true}); }
        if (req.method === 'POST' && path === '/api/amocrm/start') return json(200, {url: amocrm.start(req.headers.cookie)});
        if (req.method === 'POST' && path === '/api/amocrm/verify') return json(200, await amocrm.verify());
        if (req.method === 'GET' && ['/integrations/amocrm', '/amocrm.js'].includes(path)) {
          const script = path === '/amocrm.js';
          const contents = await readFile(new URL('./public/' + (script ? 'amocrm.js' : 'amocrm.html'), import.meta.url));
          res.writeHead(200, {'Content-Type': (script ? 'text/javascript' : 'text/html') + '; charset=utf-8'}); return res.end(contents);
        }
        return json(404, {error: 'Не найдено'});
      }
      if (req.method === 'GET' && path === '/api/state') return json(200, sync.state());
      if (req.method === 'POST' && path.startsWith('/api/')) {
        const body = await readJson(req, 2e6);
        if (path === '/api/connect') { await sync.verify(); return json(200, {ok: true}); }
        if (path === '/api/sync') {
          if (sync.state().job.running) return json(409, {error: 'Загрузка уже выполняется'});
          const numbers = body.all ? Object.keys(sync.orders) : parseNumbers(body.numbers || '');
          if (!numbers.length) return json(400, {error: 'Сначала добавьте номера накладных'});
          await sync.verify(); sync.enqueue(numbers); return json(202, {ok: true});
        }
      }
      if (req.method === 'GET' && files[path]) {
        const [name, type] = files[path];
        const contents = await readFile(new URL('./public/' + name, import.meta.url));
        res.writeHead(200, {'Content-Type': type + '; charset=utf-8'}); return res.end(contents);
      }
      json(404, {error: 'Не найдено'});
    } catch (e) { json(e.status || 400, {error: e.name === 'TimeoutError' ? 'СДЭК не ответил за 30 секунд' : e.message}); }
  });
  server.requestTimeout = 30000;
  return server;
}
