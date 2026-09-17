import {randomBytes, scrypt as scryptCallback, timingSafeEqual, createHash} from 'node:crypto';
import {promisify} from 'node:util';

const scrypt = promisify(scryptCallback);
const digest = value => createHash('sha256').update(value).digest();
const same = (a, b) => timingSafeEqual(digest(a), digest(b));

export async function hashPassword(password) {
  if (typeof password !== 'string' || password.length < 16 || password.length > 256) throw new Error('Пароль должен содержать от 16 до 256 символов');
  const salt = randomBytes(16).toString('hex');
  const key = await scrypt(password, salt, 64);
  return `scrypt$${salt}$${key.toString('hex')}`;
}

export function createAuth(env = process.env, {now = Date.now, lifetime = 12 * 60 * 60 * 1000} = {}) {
  const username = env.DASHBOARD_USERNAME;
  const hash = env.DASHBOARD_PASSWORD_HASH;
  const origin = env.APP_ORIGIN;
  const enabled = Boolean(username || hash || origin || env.NODE_ENV === 'production');
  if (!enabled) return {enabled: false, session: () => null};
  if (!/^[A-Za-z0-9._-]{1,64}$/.test(username || '') || !/^scrypt\$[a-f0-9]{32}\$[a-f0-9]{128}$/.test(hash || '')) throw new Error('Не настроены реквизиты входа');
  const url = new URL(origin);
  if (url.origin !== origin || !['http:', 'https:'].includes(url.protocol)) throw new Error('APP_ORIGIN должен содержать адрес сайта без пути');
  if (url.protocol !== 'https:' && (env.NODE_ENV === 'production' || !['localhost', '127.0.0.1'].includes(url.hostname))) throw new Error('Для публичного входа требуется HTTPS');
  const secure = url.protocol === 'https:';
  const cookieName = secure ? '__Host-amo_session' : 'amo_session';
  const sessions = new Map(), attempts = new Map();
  const windowMs = 15 * 60 * 1000;
  let globalAttempts = {until: 0, count: 0};
  const cookie = (token, seconds) => `${cookieName}=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${seconds}${secure ? '; Secure' : ''}`;
  function sessionKey(req) {
    const token = (req.headers.cookie || '').split(';').map(x => x.trim()).find(x => x.startsWith(cookieName + '='))?.slice(cookieName.length + 1);
    return token && /^[A-Za-z0-9_-]{43}$/.test(token) ? digest(token).toString('hex') : null;
  }
  function prune() {
    for (const [key, value] of sessions) if (value.expires <= now()) sessions.delete(key);
    for (const [key, value] of attempts) if (value.until <= now()) attempts.delete(key);
  }
  return {
    enabled, origin,
    session(req) {
      const key = sessionKey(req), value = sessions.get(key);
      if (!value || value.expires <= now()) { sessions.delete(key); return null; }
      return {username};
    },
    async login(req, body) {
      prune();
      // The app listens on loopback; Nginx replaces X-Real-IP with the client address.
      const ip = req.headers['x-real-ip'] || req.socket.remoteAddress;
      if (globalAttempts.until <= now()) globalAttempts = {until: now() + windowMs, count: 0};
      const attempt = attempts.get(ip) || {until: now() + windowMs, count: 0};
      if (attempt.count >= 8 || globalAttempts.count >= 100) return {status: 429, error: 'Слишком много попыток. Попробуйте через 15 минут.'};
      attempt.count++; globalAttempts.count++; attempts.set(ip, attempt);
      if (typeof body.username !== 'string' || typeof body.password !== 'string' || body.username.length > 64 || body.password.length > 256) return {status: 401, error: 'Неверный логин или пароль'};
      const [, salt, expected] = hash.split('$');
      const actual = await scrypt(body.password, salt, 64);
      if (!timingSafeEqual(actual, Buffer.from(expected, 'hex')) || !same(body.username, username)) return {status: 401, error: 'Неверный логин или пароль'};
      attempts.delete(ip);
      sessions.delete(sessionKey(req));
      if (sessions.size >= 100) sessions.delete(sessions.keys().next().value);
      const token = randomBytes(32).toString('base64url');
      sessions.set(digest(token).toString('hex'), {expires: now() + lifetime});
      return {status: 200, cookie: cookie(token, Math.floor(lifetime / 1000))};
    },
    logout(req) { sessions.delete(sessionKey(req)); return cookie('', 0); }
  };
}
