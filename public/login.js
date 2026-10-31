const form = document.querySelector('#loginForm');
const password = document.querySelector('#password');
const toggle = document.querySelector('#togglePassword');
const remember = document.querySelector('#rememberLogin');
const forget = document.querySelector('#forgetLogin');
const storageKey = 'snowbrick.saved-login';
const valid = value => value && /^[A-Za-z0-9._-]{1,64}$/.test(value.username || '') && typeof value.password === 'string' && value.password.length > 0 && value.password.length <= 256;
function saveLogin(value) {
  try {
    if (value) localStorage.setItem(storageKey, JSON.stringify(value));
    else localStorage.removeItem(storageKey);
  } catch { /* Private browser modes can disable persistent storage. */ }
  forget.hidden = !value;
}
let saved;
try { saved = JSON.parse(localStorage.getItem(storageKey)); } catch {}
// A personal link supplies credentials only in its fragment, never in HTTP requests.
const access = new URLSearchParams(location.hash.slice(1));
if (access.has('user') || access.has('key')) {
  history.replaceState(null, '', location.pathname + location.search);
  const supplied = {username: access.get('user'), password: access.get('key')};
  if (valid(supplied)) { saved = supplied; saveLogin(saved); }
}
if (valid(saved)) {
  form.username.value = saved.username; password.value = saved.password;
  remember.checked = true; forget.hidden = false;
}
forget.addEventListener('click', () => {
  saveLogin(null); remember.checked = false; password.value = ''; password.focus();
});
remember.addEventListener('change', () => { if (!remember.checked) saveLogin(null); });
toggle.addEventListener('click', () => {
  const visible = password.type === 'password';
  password.type = visible ? 'text' : 'password';
  toggle.textContent = visible ? 'Скрыть' : 'Показать';
  toggle.setAttribute('aria-label', visible ? 'Скрыть пароль' : 'Показать пароль');
  toggle.setAttribute('aria-pressed', String(visible));
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  const submit = document.querySelector('#submit'), error = document.querySelector('#error');
  submit.disabled = true; submit.textContent = 'Входим…'; error.hidden = true;
  try {
    const response = await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username: form.username.value.trim(), password: password.value})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Не удалось войти');
    saveLogin(remember.checked ? {username:form.username.value.trim(),password:password.value} : null);
    password.value = ''; location.replace('/');
  } catch (e) {
    error.textContent = e instanceof TypeError ? 'Не удалось связаться с сайтом. Проверьте подключение и попробуйте снова.' : e.message;
    error.hidden = false; submit.disabled = false; submit.textContent = 'Войти →';
  }
});
