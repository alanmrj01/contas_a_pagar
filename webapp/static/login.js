(() => {
  'use strict';
  const form = document.getElementById('loginForm');
  const button = document.getElementById('loginButton');
  const errorBox = document.getElementById('loginError');
  let csrf = '';

  async function bootstrap() {
    const response = await fetch('/api/security/bootstrap', {credentials:'same-origin', cache:'no-store'});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Não foi possível iniciar a sessão segura.');
    csrf = payload.csrf_token;
    if (payload.authenticated) window.location.replace('/');
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    errorBox.textContent = '';
    button.disabled = true;
    button.textContent = 'Entrando...';
    try {
      if (!csrf) await bootstrap();
      const response = await fetch('/api/auth/login', {
        method:'POST',
        credentials:'same-origin',
        cache:'no-store',
        headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrf},
        body:JSON.stringify({
          username:document.getElementById('username').value.trim(),
          password:document.getElementById('password').value,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      document.getElementById('password').value = '';
      if (!response.ok) throw new Error(payload.detail || 'Não foi possível entrar.');
      window.location.replace('/');
    } catch (error) {
      errorBox.textContent = String(error && error.message || error);
      csrf = '';
      await bootstrap().catch(() => {});
    } finally {
      button.disabled = false;
      button.textContent = 'Entrar';
    }
  });

  bootstrap().catch(error => { errorBox.textContent = String(error && error.message || error); });
})();
