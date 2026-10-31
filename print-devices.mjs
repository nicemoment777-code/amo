import {readFile, writeFile, rename, chmod} from 'node:fs/promises';
import {randomBytes, createHash, timingSafeEqual} from 'node:crypto';
const hash = value => createHash('sha256').update(value).digest('hex');
const equal = (a, b) => timingSafeEqual(Buffer.from(hash(a)), Buffer.from(hash(b)));

export async function createPrintDevices(file, {now = Date.now} = {}) {
  let data = {devices: {}, jobs: {}};
  try { data = JSON.parse(await readFile(file, 'utf8')); await chmod(file, 0o600); }
  catch (e) { if (e.code !== 'ENOENT') throw new Error('Не удалось прочитать устройства печати'); }
  data.events ||= {};
  const pending = new Map(), attempts = new Map();
  let tail = Promise.resolve();
  const serial = work => { const result = tail.then(work); tail = result.catch(() => {}); return result; };
  async function save(next) {
    const temp = new URL(file.toString() + '.tmp');
    await writeFile(temp, JSON.stringify(next), {mode: 0o600}); await chmod(temp, 0o600); await rename(temp, file); data = next;
  }
  function prune() {
    for (const [key, item] of pending) if (item.until <= now()) pending.delete(key);
    for (const [key, item] of attempts) if (item.until <= now()) attempts.delete(key);
  }
  function validId(id) { if (!/^\d{1,20}$/.test(String(id))) throw new Error('Некорректная заявка'); return String(id); }
  return {
    begin(body, ip) {
      prune();
      if (!/^[a-f0-9]{64}$/.test(body.tokenHash || '')) throw new Error('Некорректный ключ устройства');
      const limit = attempts.get(ip) || {count: 0, until: now() + 600000};
      if (limit.count >= 5 || pending.size >= 50) throw new Error('Слишком много запросов подключения. Повторите через 10 минут.');
      limit.count++; attempts.set(ip, limit);
      const requestId = randomBytes(24).toString('base64url'), pollSecret = randomBytes(32).toString('base64url');
      let code;
      do { code = randomBytes(4).toString('hex').toUpperCase(); } while ([...pending.values()].some(p => p.code === code));
      pending.set(requestId, {code, pollHash: hash(pollSecret), tokenHash: body.tokenHash, until: now() + 600000, approved: false});
      return {requestId, pollSecret, code, expiresIn: 600};
    },
    poll(body) {
      prune(); const item = pending.get(body.requestId);
      if (!item || typeof body.pollSecret !== 'string' || !equal(item.pollHash, hash(body.pollSecret))) throw new Error('Подключение истекло. Получите новый код.');
      return {approved: item.approved};
    },
    approve: body => serial(async () => {
      prune();
      const code = String(body.code || '').replace(/[-\s]/g, '').toUpperCase();
      const item = [...pending.values()].find(p => p.code === code && !p.approved);
      if (!item) throw new Error('Код не найден или истёк');
      const name = String(body.name || 'Компьютер печати').trim();
      if (!name || name.length > 80) throw new Error('Название: от 1 до 80 символов');
      await save({...data, devices: {...data.devices, [item.tokenHash]: {name, createdAt: now(), revoked: false}}});
      item.approved = true;
      return {ok: true};
    }),
    authorize(token) {
      if (typeof token !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(token)) return null;
      const id = hash(token); return data.devices[id] && !data.devices[id].revoked ? id : null;
    },
    list: () => Object.entries(data.devices).map(([id, item]) => ({id, name: item.name, revoked: item.revoked})),
    revoke: id => serial(async () => { if (!data.devices[id]) throw new Error('Устройство не найдено'); await save({...data, devices: {...data.devices, [id]: {...data.devices[id], revoked: true}}}); return {ok: true}; }),
    history: () => ({
      printed: Object.fromEntries(Object.entries(data.jobs).filter(([,v])=>v.status==='printed').map(([id,v])=>[id,{at:Math.floor(v.at/1000),status:'submitted'}])),
      uncertain: Object.fromEntries(Object.entries(data.jobs).filter(([,v])=>v.status==='claimed').map(([id,v])=>[id,{at:Math.floor(v.at/1000),status:'reserved-on-server'}])),
      events: Object.values(data.events)
    }),
    record: (entries, owner) => serial(async () => {
      if (!Array.isArray(entries) || entries.length>100) throw new Error('Некорректный журнал печати');
      const events={...data.events}, jobs={...data.jobs};
      for (const entry of entries) {
        const id=validId(entry.id), eventId=entry.eventId;
        if (!/^[a-f0-9]{64}$/.test(eventId || '') || !Number.isSafeInteger(entry.at) || entry.at<0 || entry.at>Math.floor(now()/1000)+300 ||
            entry.status!=='submitted' || typeof entry.printer!=='string' || entry.printer.length>256) throw new Error('Некорректная запись печати');
        const key=hash(owner+':'+eventId);
        const value={id,eventId,at:entry.at,printer:entry.printer,status:'submitted',mode:entry.mode==='auto'?'auto':'manual'};
        if (events[key]) {
          if (JSON.stringify(events[key])!==JSON.stringify(value)) throw new Error('Запись печати уже сохранена с другими данными');
          continue;
        }
        events[key]=value;
        if (jobs[id]?.status!=='printed' || jobs[id].at<entry.at*1000) jobs[id]={owner,status:'printed',at:entry.at*1000};
      }
      await save({...data,events,jobs});
      return {ok:true};
    }),
    claim: (id, owner) => serial(async () => {
      id = validId(id);
      if (data.jobs[id]) return {claimed: false};
      await save({...data, jobs: {...data.jobs, [id]: {owner, status: 'claimed', at: now()}}}); return {claimed: true};
    }),
    complete: (id, owner) => serial(async () => {
      id = validId(id); const job = data.jobs[id];
      if (!job || job.owner !== owner) throw new Error('Задание принадлежит другому устройству');
      await save({...data, jobs: {...data.jobs, [id]: {...job, status: 'printed', at: now()}}}); return {ok: true};
    })
  };
}
