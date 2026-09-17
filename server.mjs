import {mkdir} from 'node:fs/promises';
import {CdekClient} from './cdek.mjs';
import {createSync} from './sync-service.mjs';
import {createAuth} from './auth.mjs';
import {createApp} from './http-app.mjs';

const port = Number(process.env.PORT || 3080);
const auth = createAuth(); // Refuse incomplete production credentials before starting any work.
const client = new CdekClient(process.env.CDEK_CLIENT_ID || process.env.AMO_ACCOUNT_ID, process.env.CDEK_CLIENT_SECRET || process.env.AMO_PASSWORD);
await mkdir(new URL('./data/', import.meta.url), {recursive: true});
const sync = await createSync(client, new URL('./data/', import.meta.url), process.env.SYNC_INTERVAL_MINUTES);
const server = createApp({sync, auth, webhookSecret: process.env.CDEK_WEBHOOK_SECRET});
server.listen(port, '127.0.0.1', () => { console.log(`CDEK dashboard: http://127.0.0.1:${port}`); sync.start(); });
