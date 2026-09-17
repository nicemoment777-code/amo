import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {parseNumbers} from './cdek.mjs';
import {validWebhookKey, webhookOrder} from './webhook.mjs';

const files = {'/': ['index.html', 'text/html'], '/app.js': ['app.js', 'text/javascript'], '/colors.js': ['colors.js', 'text/javascript'], '/style.css': ['style.css', 'text/css'], '/login': ['login.html', 'text/html'], '/login.js': ['login.js', 'text/javascript'], '/login.css': ['login.css', 'text/css']};
const publicPaths = new Set(['/login', '/login.js', '/login.css']);
async function readJson(req, limit) {
  if (req.headers['content-type']?.split(';')[0].trim() !== 'application/json') throw Object.assign(new Error('Требуется JSON'), {status: 415});
  let size = 0; const chunks = [];
  for await (const chunk of req) { size += chunk.length; if (size > limit) throw Object.assign(new Error('Слишком большой запрос'), {status: 413}); chunks.push(chunk); }
  try { const value = JSON.parse(Buffer.concat(chunks).toString() || '{}'); if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(); return value; }
  catch { throw new Error('Некорректный JSON'); }
}

export function createApp({sync, auth, webhookSecret}) {
  const server = http.createServer(async (req, res) => {
    const json = (status, value) => { res.writeHead(status, {'Content-Type': 'application/json; charset=utf-8'}); res.end(JSON.stringify(value)); };
    const redirect = path => { res.writeHead(302, {Location: path}); res.end(); };
    res.setHeader('Cache-Control', 'no-store'); res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
    try {
      const path = new URL(req.url, 'http://localhost').pathname;
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
      if (req.method === 'GET' && path === '/login' && (!auth.enabled || session)) return redirect('/');
      if (auth.enabled && !session && !publicPaths.has(path)) {
        if (path.startsWith('/api/')) return json(401, {error: 'Войдите в аккаунт'});
        return redirect('/login');
      }
      if (req.method === 'GET' && path === '/api/auth/session') return json(200, {enabled: auth.enabled, username: session?.username});
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
