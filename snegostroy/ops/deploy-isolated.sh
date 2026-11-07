#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "Deployment check failed at line %s\n" "$LINENO" >&2' ERR
release=${1:?release SHA is required}
[[ "$release" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid release SHA'; exit 1; }
bundle="/tmp/snegostroy-$release.tgz"
root=/var/www/snegostroy
target="$root/releases/$release"
config=/etc/nginx/sites-available/amo
snippet=/etc/nginx/snippets/snegostroy-777.conf
test -f "$bundle"
test -f "$config"
before_pid=$(systemctl show amo.service --property=MainPID --value)
before_health=$(curl -fsS --max-time 10 http://127.0.0.1:3080/healthz | sha256sum | cut -d' ' -f1)
before_login=$(curl -fsS --max-time 10 https://snowbrick.ru/login | sha256sum | cut -d' ' -f1)
mkdir -p "$target"
tar -xzf "$bundle" -C "$target" --no-same-owner
test -s "$target/dist/index.html"
test -s "$target/dist/app.js"
test -s "$target/dist/vendor/three.module.js"
find "$target" -type d -exec chmod 755 {} +
find "$target" -type f -exec chmod 644 {} +
backup="$root/nginx-before-$release.conf"
cp -p "$config" "$backup"
previous=$(readlink "$root/current" || true)
ln -sfn "$target/dist" "$root/current-next"
mv -Tf "$root/current-next" "$root/current"
cp "$target/ops/snegostroy-777.conf" "$snippet"
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/nginx/sites-available/amo')
text=p.read_text()
line='    include /etc/nginx/snippets/snegostroy-777.conf;\n'
if line.strip() not in text:
    marker='    location / {'
    if text.count(marker)!=1:
        raise SystemExit('Expected exactly one original proxy location; no configuration was changed')
    text=text.replace(marker,line+'\n'+marker,1)
    p.write_text(text)
PY
if ! nginx -t; then
    cp -p "$backup" "$config"
    if [[ -n "$previous" ]]; then ln -s "$previous" "$root/current-rollback"; mv -Tf "$root/current-rollback" "$root/current"; fi
    echo 'Nginx validation failed; shared configuration restored'; exit 1
fi
systemctl reload nginx
ready=false
for attempt in {1..15}; do
    if curl -fsS --max-time 5 https://snowbrick.ru/777/ -o "$root/verify-$release.html" && cmp -s "$root/verify-$release.html" "$target/dist/index.html"; then
        ready=true
        break
    fi
    sleep 1
done
[[ "$ready" == true ]] || { echo 'New route did not become ready'; exit 1; }
curl -fsS --max-time 15 https://snowbrick.ru/777/app.js >/dev/null
curl -fsS --max-time 15 https://snowbrick.ru/777/vendor/three.module.js >/dev/null
after_pid=$(systemctl show amo.service --property=MainPID --value)
after_health=$(curl -fsS --max-time 10 http://127.0.0.1:3080/healthz | sha256sum | cut -d' ' -f1)
after_login=$(curl -fsS --max-time 10 https://snowbrick.ru/login | sha256sum | cut -d' ' -f1)
[[ "$before_pid" == "$after_pid" ]] || { echo 'Existing service PID changed'; exit 1; }
[[ "$before_health" == "$after_health" ]] || { echo 'Existing health response changed'; exit 1; }
[[ "$before_login" == "$after_login" ]] || { echo 'Existing login response changed'; exit 1; }
printf 'SNEGOSTROY_PUBLISHED https://snowbrick.ru/777/\nEXISTING_SERVICE_UNCHANGED true\n'
