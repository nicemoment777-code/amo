// Run as root on the VPS. Never print the password or password hash.
import {readFile, writeFile, chmod, appendFile} from 'node:fs/promises';
import {randomBytes} from 'node:crypto';
import {hashPassword} from '../auth.mjs';
const domain = process.argv[2];
if (!/^[a-z0-9.-]+$/i.test(domain || '')) throw new Error('Invalid domain');
const file = '/root/amo-dashboard-credentials.json';
let credentials;
try { credentials = JSON.parse(await readFile(file, 'utf8')); }
catch (error) {
  if (error.code !== 'ENOENT') throw error;
  // Preserve credentials when upgrading the earlier Basic Auth deployment.
  try {
    const text = await readFile('/root/amo-dashboard-credentials.txt', 'utf8');
    credentials = {username: text.match(/^USER=(.+)$/m)?.[1], password: text.match(/^PASSWORD=(.+)$/m)?.[1]};
  } catch (legacyError) { if (legacyError.code !== 'ENOENT') throw legacyError; }
  credentials ||= {username: 'admin', password: randomBytes(18).toString('base64url')};
}
if (!/^[A-Za-z0-9._-]{1,64}$/.test(credentials.username || '')) throw new Error('Invalid dashboard username');
const hash = await hashPassword(credentials.password);
credentials.url = `https://${domain}/login`;
await writeFile(file, JSON.stringify(credentials, null, 2), {mode: 0o600}); await chmod(file, 0o600);
await writeFile('/root/amo-dashboard-credentials.txt', `URL=${credentials.url}\nUSER=${credentials.username}\nPASSWORD=${credentials.password}\n`, {mode: 0o600});
await chmod('/root/amo-dashboard-credentials.txt', 0o600);
await appendFile('/etc/amo.env.next', `NODE_ENV=production\nAPP_ORIGIN=https://${domain}\nDASHBOARD_USERNAME=${credentials.username}\nDASHBOARD_PASSWORD_HASH='${hash}'\n`);
console.log('Dashboard login configured; existing credentials preserved.');
