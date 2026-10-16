const message = document.querySelector('#message');
const settings = document.querySelector('#settings');
const connect = document.querySelector('#connect');
const verify = document.querySelector('#verify');
async function api(path, body) {
  const response = await fetch('/api/amocrm/' + path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Не удалось выполнить запрос');
  return data;
}
async function update() {
  const data = await api('status');
  document.querySelector('#redirectUri').textContent = data.redirectUri;
  document.querySelector('#status').textContent = data.connected ? 'Токены сохранены. Нажмите «Проверить подключение», чтобы проверить доступ.' : data.configured ? 'Ключи сохранены. Разрешите доступ в amoCRM.' : 'Ключи ещё не сохранены.';
  connect.disabled = !data.configured; verify.disabled = !data.connected;
}
async function run(button, action) {
  button.disabled = true; message.textContent = '';
  try { await action(); } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
}
settings.addEventListener('submit', event => {
  event.preventDefault();
  run(settings.querySelector('button'), async () => {
    await api('configure', {clientId: settings.clientId.value, clientSecret: settings.clientSecret.value});
    settings.reset(); await update(); message.textContent = 'Ключи сохранены.';
  });
});
connect.addEventListener('click', () => run(connect, async () => { const data = await api('start', {}); location.assign(data.url); }));
verify.addEventListener('click', () => run(verify, async () => { await api('verify', {}); await update(); message.textContent = 'Подключение к snegostroy.amocrm.ru проверено.'; }));
const result = new URLSearchParams(location.search).get('result');
if (result) {
  message.textContent = result === 'ok' ? 'Авторизация завершена. Проверьте подключение.' : 'Авторизация не завершена. Войдите на сайт и повторите подключение через кнопку ниже.';
  history.replaceState(null, '', '/integrations/amocrm');
}
update().catch(error => { message.textContent = error.message; });
async function devices() {
  const data = await api('devices');
  const root = document.querySelector('#devices'); root.replaceChildren();
  for (const device of data.devices) {
    const row = document.createElement('p');
    row.textContent = device.name + (device.revoked ? ' — доступ отключён' : ' — подключён');
    if (!device.revoked) {
      const button = document.createElement('button'); button.textContent = 'Отключить доступ';
      button.addEventListener('click', () => run(button, async () => { await api('devices/revoke', {id:device.id}); await devices(); }));
      row.append(' ', button);
    }
    root.append(row);
  }
}
document.querySelector('#pairDevice').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  run(form.querySelector('button'), async () => {
    await api('devices/approve', {code:form.elements.namedItem('code').value, name:form.elements.namedItem('name').value});
    form.elements.namedItem('code').value = ''; message.textContent = 'Компьютер подключён. Вернитесь в приложение Windows.'; await devices();
  });
});
devices().catch(error => { message.textContent = error.message; });
