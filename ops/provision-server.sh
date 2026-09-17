#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Этот скрипт должен запускаться от root" >&2
  exit 1
fi

DEPLOY_SHA=${1:?Нужен SHA релиза}
DOMAIN=${2:?Нужен домен}
ARCHIVE=/root/amo-release.tgz
ENV_IN=/root/amo.env.new
DASH_USER_FILE=/root/amo-dashboard-user
DASH_PASSWORD_FILE=/root/amo-dashboard-password
ORDER_NUMBERS_FILE=/root/amo-order-numbers
CREDENTIALS_FILE=/root/amo-dashboard-credentials.txt

for f in "$ARCHIVE" "$ENV_IN"; do
  [[ -s "$f" ]] || { echo "Нет обязательного файла $f" >&2; exit 1; }
done

if [[ ! -s "$DASH_USER_FILE" ]]; then printf 'admin' > "$DASH_USER_FILE"; fi
if [[ ! -s "$DASH_PASSWORD_FILE" ]]; then umask 077; openssl rand -base64 24 | tr -d '\n' > "$DASH_PASSWORD_FILE"; fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git nginx apache2-utils certbot python3-certbot-nginx openssh-server openssl

if ! command -v node >/dev/null 2>&1 || [[ $(node -p 'Number(process.versions.node.split(".")[0])') -lt 22 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_24.x | bash -
  apt-get install -y nodejs
fi
node --version

systemctl enable --now ssh.service >/dev/null 2>&1 || true
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow OpenSSH >/dev/null
  ufw allow 'Nginx Full' >/dev/null
fi

if ! id amo >/dev/null 2>&1; then
  useradd --system --home /opt/amo --shell /usr/sbin/nologin amo
fi
install -d -o root -g root -m 0755 /opt/amo /opt/amo/releases
install -d -o amo -g amo -m 0750 /var/lib/amo

RELEASE="/opt/amo/releases/$DEPLOY_SHA"
rm -rf "$RELEASE"
install -d -o root -g root -m 0755 "$RELEASE"
tar -xzf "$ARCHIVE" -C "$RELEASE"
rm -rf "$RELEASE/data"
ln -s /var/lib/amo "$RELEASE/data"

cd "$RELEASE"
node --test

install -m 0600 -o root -g root "$ENV_IN" /etc/amo.env.next
WEBHOOK_SECRET=""
if [[ -f /etc/amo.env ]]; then
  WEBHOOK_SECRET=$(sed -n 's/^CDEK_WEBHOOK_SECRET="\(.*\)"$/\1/p' /etc/amo.env | tail -n1 || true)
fi
if [[ -z "$WEBHOOK_SECRET" ]]; then WEBHOOK_SECRET=$(openssl rand -hex 32); fi
printf 'CDEK_WEBHOOK_SECRET="%s"\n' "$WEBHOOK_SECRET" >> /etc/amo.env.next
mv /etc/amo.env.next /etc/amo.env
chmod 0600 /etc/amo.env

ln -sfn "$RELEASE" /opt/amo/current
cat >/etc/systemd/system/amo.service <<'UNIT'
[Unit]
Description=CDEK orders dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=amo
Group=amo
WorkingDirectory=/opt/amo/current
EnvironmentFile=/etc/amo.env
ExecStart=/usr/bin/node server.mjs
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/amo

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now amo.service
systemctl restart amo.service

for _ in {1..30}; do
  curl -fsS --max-time 2 http://127.0.0.1:3080/api/state >/dev/null && break
  sleep 1
done
curl -fsS --max-time 5 http://127.0.0.1:3080/api/state >/dev/null

DASH_USER=$(cat "$DASH_USER_FILE")
DASH_PASSWORD=$(cat "$DASH_PASSWORD_FILE")
if [[ ! "$DASH_USER" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then echo "Недопустимое имя пользователя панели" >&2; exit 1; fi
htpasswd -cbB /etc/nginx/amo.htpasswd "$DASH_USER" "$DASH_PASSWORD" >/dev/null
chown root:www-data /etc/nginx/amo.htpasswd
chmod 0640 /etc/nginx/amo.htpasswd
umask 077
printf 'URL=https://%s/\nUSER=%s\nPASSWORD=%s\n' "$DOMAIN" "$DASH_USER" "$DASH_PASSWORD" > "$CREDENTIALS_FILE"
chmod 0600 "$CREDENTIALS_FILE"

cat >/etc/nginx/sites-available/amo <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    client_max_body_size 2m;

    location ^~ /webhooks/cdek/ {
        access_log off;
        proxy_set_header Host 127.0.0.1:3080;
        proxy_pass http://127.0.0.1:3080;
    }

    location / {
        auth_basic "CDEK Orders";
        auth_basic_user_file /etc/nginx/amo.htpasswd;
        proxy_set_header Host 127.0.0.1:3080;
        proxy_set_header Origin http://127.0.0.1:3080;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_pass http://127.0.0.1:3080;
    }
}
NGINX
ln -sfn /etc/nginx/sites-available/amo /etc/nginx/sites-enabled/amo
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect
nginx -t
systemctl reload nginx

if [[ -s "$ORDER_NUMBERS_FILE" ]]; then
  python3 - "$ORDER_NUMBERS_FILE" >/tmp/amo-sync-body.json <<'PY'
import json, re, sys
text = open(sys.argv[1], encoding='utf-8').read()
nums = [x for x in re.split(r'[\s,;]+', text) if x]
if not nums or any(not re.fullmatch(r'\d{5,20}', x) for x in nums): raise SystemExit('Некорректный CDEK_ORDER_NUMBERS')
print(json.dumps({'numbers': ' '.join(dict.fromkeys(nums))}, ensure_ascii=False))
PY
  curl -fsS -X POST http://127.0.0.1:3080/api/sync -H 'Content-Type: application/json' --data-binary @/tmp/amo-sync-body.json >/dev/null
  for _ in {1..90}; do
    STATE=$(curl -fsS http://127.0.0.1:3080/api/state | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d.get("orders",[])), d.get("pendingCount",0), int(bool(d.get("job",{}).get("running"))), len(d.get("job",{}).get("errors",[])))')
    read -r ORDER_COUNT PENDING RUNNING ERRORS <<<"$STATE"
    if [[ "$PENDING" == 0 && "$RUNNING" == 0 ]]; then echo "СДЭК: загружено заказов $ORDER_COUNT; ошибок последней синхронизации $ERRORS"; break; fi
    sleep 2
  done
fi

set -a
. /etc/amo.env
set +a
node --input-type=module <<'NODE'
const id = process.env.CDEK_CLIENT_ID || process.env.AMO_ACCOUNT_ID;
const secret = process.env.CDEK_CLIENT_SECRET || process.env.AMO_PASSWORD;
const domain = process.env.VPS_DOMAIN_FOR_WEBHOOK;
const hookSecret = process.env.CDEK_WEBHOOK_SECRET;
if (!id || !secret || !domain || !hookSecret) throw new Error('Не хватает данных для webhook СДЭК');
const tokenResponse = await fetch('https://api.cdek.ru/v2/oauth/token', {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'client_credentials',client_id:id,client_secret:secret}),signal:AbortSignal.timeout(30000)});
if (!tokenResponse.ok) throw new Error(`СДЭК OAuth: ${tokenResponse.status}`);
const token=(await tokenResponse.json()).access_token;
const auth={Authorization:`Bearer ${token}`};
const desiredUrl=`https://${domain}/webhooks/cdek/${hookSecret}`;
const listResponse=await fetch('https://api.cdek.ru/v2/webhooks',{headers:auth,signal:AbortSignal.timeout(30000)});
if (!listResponse.ok) throw new Error(`СДЭК список webhook: ${listResponse.status}`);
const data=await listResponse.json(); let exists=false; const seen=new Set();
function walk(v){if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);if(v.type==='ORDER_STATUS'&&v.url===desiredUrl)exists=true;if(Array.isArray(v))for(const x of v)walk(x);else for(const x of Object.values(v))walk(x)}
walk(data);
if(!exists){const r=await fetch('https://api.cdek.ru/v2/webhooks',{method:'POST',headers:{...auth,'Content-Type':'application/json'},body:JSON.stringify({type:'ORDER_STATUS',url:desiredUrl}),signal:AbortSignal.timeout(30000)});if(!r.ok)throw new Error(`СДЭК создание webhook: ${r.status}`);console.log('СДЭК: подписка ORDER_STATUS создана')}else console.log('СДЭК: нужная подписка ORDER_STATUS уже существует');
NODE

STATUS_NOAUTH=$(curl -ksS -o /dev/null -w '%{http_code}' "https://$DOMAIN/")
[[ "$STATUS_NOAUTH" == 401 ]] || { echo "Ожидался HTTP 401 без авторизации, получен $STATUS_NOAUTH" >&2; exit 1; }
echo "HTTPS работает; панель защищена Basic Auth; сервис amo активен."
systemctl --no-pager --full status amo.service | sed -n '1,12p'

rm -f "$ARCHIVE" "$ENV_IN" "$DASH_USER_FILE" "$DASH_PASSWORD_FILE" "$ORDER_NUMBERS_FILE" /tmp/amo-sync-body.json
