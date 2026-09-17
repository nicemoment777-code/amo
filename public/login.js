const form = document.querySelector('#loginForm');
const password = document.querySelector('#password');
const toggle = document.querySelector('#togglePassword');
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
    password.value = ''; location.replace('/');
  } catch (e) {
    error.textContent = e instanceof TypeError ? 'Не удалось связаться с сайтом. Проверьте подключение и попробуйте снова.' : e.message;
    error.hidden = false; submit.disabled = false; submit.textContent = 'Войти →';
  }
});
