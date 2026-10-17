import {readFile, writeFile, rename, chmod} from 'node:fs/promises';
import {randomBytes, createHash} from 'node:crypto';
import {deliveryInfo} from './delivery-service.mjs';

export const callbackPath = '/integrations/amocrm/callback';
const account = 'snegostroy.amocrm.ru';
const fingerprint = value => createHash('sha256').update(value || '').digest('hex');

// Secrets never leave this service. All writes are serialized, including token rotation.
export async function createAmoCrm(file, origin, {fetcher = fetch, now = Date.now} = {}) {
  let stored = {};
  try { stored = JSON.parse(await readFile(file, 'utf8')); await chmod(file, 0o600); }
  catch (error) { if (error.code !== 'ENOENT') throw new Error('Не удалось прочитать настройки amoCRM'); }
  const redirectUri = origin ? origin + callbackPath : null;
  const pending = new Map();
  let retryAfter = 0;
  let tail = Promise.resolve();
  const serial = work => { const result = tail.then(work); tail = result.catch(() => {}); return result; };
  async function save(value) {
    const temp = new URL(file.toString() + '.tmp');
    await writeFile(temp, JSON.stringify(value), {mode: 0o600});
    await chmod(temp, 0o600);
    await rename(temp, file);
    stored = value;
  }
  function ready() {
    if (!redirectUri?.startsWith('https://') || !stored.clientId || !stored.clientSecret) throw new Error('Сначала сохраните ID и секретный ключ интеграции');
  }
  async function exchange(grant) {
    ready();
    let data;
    try {
      const response = await fetcher(`https://${account}/oauth2/access_token`, {
        method: 'POST', redirect: 'error', signal: AbortSignal.timeout(30000),
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({client_id: stored.clientId, client_secret: stored.clientSecret, redirect_uri: redirectUri, ...grant})
      });
      if (!response.ok) throw new Error();
      data = await response.json();
      if (typeof data.access_token !== 'string' || !data.access_token || typeof data.refresh_token !== 'string' || !data.refresh_token || !Number.isFinite(data.expires_in) || data.expires_in <= 0) throw new Error();
    } catch { throw new Error('amoCRM не выдала токены. Проверьте ключи и повторите авторизацию.'); }
    await save({...stored, accessToken: data.access_token, refreshToken: data.refresh_token, expiresAt: now() + data.expires_in * 1000});
  }
  async function accessToken() {
    if (!stored.refreshToken) throw new Error('Сначала разрешите доступ в amoCRM');
    if (stored.expiresAt <= now() + 60000) await exchange({grant_type: 'refresh_token', refresh_token: stored.refreshToken});
    return stored.accessToken;
  }
  async function get(path) {
    const token = await accessToken();
    const response = await fetcher(`https://${account}${path}`, {headers: {Authorization: `Bearer ${token}`}, redirect: 'error', signal: AbortSignal.timeout(30000)});
    if (response.status === 204) return {};
    if (!response.ok) throw new Error(`Не удалось прочитать amoCRM (${response.status})`);
    return response.json();
  }
  const fieldText = (lead, name) => (lead.custom_fields_values || []).filter(f => f.field_name?.trim().toLowerCase() === name.toLowerCase()).flatMap(f => f.values || []).map(v => v.value).filter(v => typeof v === 'string').join('\n').trim();
  function printItem(lead) {
    const {label, service:deliveryService} = deliveryInfo(lead);
    const composition = fieldText(lead, 'Состав заказа');
    let labelHost = null;
    try { labelHost = new URL(label).hostname; } catch {}
    const orderValue = name => (lead.custom_fields_values || [])
      .filter(f => f.field_name?.trim().toLowerCase() === name.toLowerCase())
      .flatMap(f => f.values || []).map(v => v.value)
      .find(value => (typeof value === 'string' && value.trim()) || (typeof value === 'number' && Number.isSafeInteger(value)));
    const orderNumber = orderValue('ORDERID') ?? orderValue('Номер заказа');
    return {id: lead.id, orderNumber: orderNumber == null ? null : String(orderNumber).trim(), deliveryService, createdAt: lead.created_at, pipelineId: lead.pipeline_id, composition, hasLabel: Boolean(labelHost), labelHost};
  }
  return {
    printCandidates: (from, sample = false) => serial(async () => {
      const items = []; const names = new Set();
      for (let page = 1; page <= 40; page++) {
        const query = new URLSearchParams({'limit': '250', page: String(page), 'filter[pipeline_id]': '8604134', 'order[created_at]': sample ? 'desc' : 'asc'});
        if (!sample) query.set('filter[created_at][from]', String(from));
        const data = await get('/api/v4/leads?' + query);
        const leads = data._embedded?.leads || [];
        for (const lead of leads) {
          for (const field of lead.custom_fields_values || []) names.add(field.field_name);
          items.push(printItem(lead));
        }
        if (sample || !data._links?.next) return {items, fieldNames: [...names].filter(Boolean)};
      }
      throw new Error('Слишком много заявок. Проверка остановлена без пропуска страниц.');
    }),
    printLabel: id => serial(async () => {
      const lead = await get('/api/v4/leads/' + id);
      if (lead.pipeline_id !== 8604134) throw new Error('Заявка находится в другой воронке');
      return {item: printItem(lead), url: deliveryInfo(lead).label};
    }),
    status: () => ({account, redirectUri, configured: Boolean(stored.clientId && stored.clientSecret), connected: Boolean(stored.refreshToken), expiresAt: stored.expiresAt || null}),
    configure: body => serial(async () => {
      if (!redirectUri?.startsWith('https://')) throw new Error('Для подключения требуется настроенный HTTPS и вход на сайт');
      const clientId = typeof body.clientId === 'string' ? body.clientId.trim() : '';
      const clientSecret = typeof body.clientSecret === 'string' ? body.clientSecret.trim() : '';
      if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(clientId) || clientSecret.length < 16 || clientSecret.length > 4096 || /\s/.test(clientSecret)) throw new Error('Укажите корректные ID и секретный ключ интеграции');
      await save({clientId, clientSecret}); pending.clear();
    }),
    start(cookie) {
      ready();
      for (const [key, value] of pending) if (value.expires <= now()) pending.delete(key);
      if (pending.size >= 100) throw new Error('Слишком много попыток подключения');
      const state = randomBytes(32).toString('base64url');
      pending.set(state, {session: fingerprint(cookie), expires: now() + 10 * 60000});
      const url = new URL('https://www.amocrm.ru/oauth');
      url.search = new URLSearchParams({client_id: stored.clientId, state, mode: 'post_message'}).toString();
      return url.href;
    },
    callback: (params, cookie) => serial(async () => {
      const state = params.get('state'), item = pending.get(state);
      if (!item || item.expires <= now() || item.session !== fingerprint(cookie)) throw new Error('Авторизация истекла. Начните подключение заново.');
      pending.delete(state);
      if (params.has('error')) throw new Error('Доступ в amoCRM не предоставлен');
      if (params.get('referer') !== account || !params.get('code') || params.get('code').length > 8192) throw new Error('Некорректный ответ авторизации amoCRM');
      await exchange({grant_type: 'authorization_code', code: params.get('code')});
    }),
    verify: () => serial(async () => {
      const token = await accessToken();
      try {
        const response = await fetcher(`https://${account}/api/v4/account`, {headers: {Authorization: `Bearer ${token}`}, redirect: 'error', signal: AbortSignal.timeout(30000)});
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (data.subdomain !== 'snegostroy') throw new Error();
      } catch { throw new Error('Не удалось проверить доступ к аккаунту amoCRM. Повторите авторизацию.'); }
      return {ok: true};
    }),
    refreshDue: () => serial(async () => {
      if (!stored.refreshToken || stored.expiresAt > now() + 60000 || retryAfter > now()) return;
      try { await accessToken(); retryAfter = 0; }
      catch { retryAfter = now() + 15 * 60000; }
    })
  };
}
