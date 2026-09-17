#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Этот скрипт должен запускаться от root" >&2
  exit 1
fi

DEPLOY_SHA=${1:?Нужен SHA релиза}
DOMAIN=${2:?Нужен домен}
[[ "$DEPLOY_SHA" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid release SHA'; exit 1; }
[[ "$DOMAIN" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9]$ ]] || { echo 'Invalid domain'; exit 1; }
umask 077
ARCHIVE=/root/amo-release.tgz
ENV_IN=/root/amo.env.new
ORDER_NUMBERS_FILE=/root/amo-order-numbers

for f in "$ARCHIVE" "$ENV_IN"; do
  [[ -s "$f" ]] || { echo "Нет обязательного файла $f" >&2; exit 1; }
done


export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git nginx certbot python3-certbot-nginx openssh-server openssl

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
node ops/configure-auth.mjs "$DOMAIN"
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
  curl -fsS --max-time 2 http://127.0.0.1:3080/healthz >/dev/null && break
  sleep 1
done
curl -fsS --max-time 5 http://127.0.0.1:3080/healthz >/dev/null

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
        proxy_set_header Host 127.0.0.1:3080;
        proxy_set_header X-Real-IP \$remote_addr;
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

CERT_DOMAINS=(-d "$DOMAIN")
if [[ "$(getent ahostsv4 "www.$DOMAIN" | awk '{print $1}' | sort -u)" == "$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u)" ]]; then
  cat >>/etc/nginx/sites-available/amo <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name www.$DOMAIN;
    return 301 https://$DOMAIN\$request_uri;
}
NGINX
  CERT_DOMAINS+=(-d "www.$DOMAIN")
fi
nginx -t
systemctl reload nginx
certbot --nginx "${CERT_DOMAINS[@]}" --non-interactive --agree-tos --register-unsafely-without-email --redirect
nginx -t
systemctl reload nginx

node ops/check-deployment.mjs

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

echo "HTTPS работает; настроена страница входа; сервис amo активен."
systemctl is-active amo.service

rm -f "$ARCHIVE" "$ENV_IN" "$ORDER_NUMBERS_FILE"
