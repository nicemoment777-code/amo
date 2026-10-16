import {mkdir} from 'node:fs/promises';
import {CdekClient} from './cdek.mjs';
import {createSync} from './sync-service.mjs';
import {createAuth} from './auth.mjs';
import {createApp} from './http-app.mjs';
import {createAmoCrm} from './amocrm.mjs';
import {createPrintDevices} from './print-devices.mjs';

const port = Number(process.env.PORT || 3080);
const auth = createAuth(); // Refuse incomplete production credentials before starting any work.
const client = new CdekClient(process.env.CDEK_CLIENT_ID || process.env.AMO_ACCOUNT_ID, process.env.CDEK_CLIENT_SECRET || process.env.AMO_PASSWORD);
await mkdir(new URL('./data/', import.meta.url), {recursive: true});
const sync = await createSync(client, new URL('./data/', import.meta.url), process.env.SYNC_INTERVAL_MINUTES);
const amocrm = await createAmoCrm(new URL('./data/amocrm.json', import.meta.url), auth.origin);
const printDevices = await createPrintDevices(new URL('./data/print-devices.json', import.meta.url));
const refreshTimer = setInterval(() => { amocrm.refreshDue().catch(() => {}); }, 60000);
refreshTimer.unref();
const server = createApp({sync, auth, webhookSecret: process.env.CDEK_WEBHOOK_SECRET, amocrm, printAgentHash: process.env.PRINT_AGENT_TOKEN_HASH, labelHosts: (process.env.PRINT_LABEL_HOSTS || '').split(',').filter(Boolean), printDevices});
server.listen(port, '127.0.0.1', () => { console.log(`CDEK dashboard: http://127.0.0.1:${port}`); sync.start(); });
