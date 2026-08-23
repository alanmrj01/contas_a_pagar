(() => {
  'use strict';
  const form = document.getElementById('loginForm');
  const button = document.getElementById('loginButton');
  const errorBox = document.getElementById('loginError');
  const emailInput = document.getElementById('email');
  const passwordInput = document.getElementById('password');
  const togglePassword = document.getElementById('togglePassword');
  const forgotPassword = document.getElementById('forgotPassword');
  const recoveryPanel = document.getElementById('recoveryPanel');
  const recoveryRequestForm = document.getElementById('recoveryRequestForm');
  const recoveryVerifyForm = document.getElementById('recoveryVerifyForm');
  const recoveryUpdateForm = document.getElementById('recoveryUpdateForm');
  const recoveryEmail = document.getElementById('recoveryEmail');
  const recoveryCode = document.getElementById('recoveryCode');
  const newPassword = document.getElementById('newPassword');
  const confirmNewPassword = document.getElementById('confirmNewPassword');
  const recoveryMessage = document.getElementById('recoveryMessage');
  const recoveryError = document.getElementById('recoveryError');
  const sendRecoveryCode = document.getElementById('sendRecoveryCode');
  const verifyRecoveryCode = document.getElementById('verifyRecoveryCode');
  const updateRecoveredPassword = document.getElementById('updateRecoveredPassword');
  const resendRecoveryCode = document.getElementById('resendRecoveryCode');
  const backToLogin = document.getElementById('backToLogin');
  let csrf = '';
  let requestedRecoveryEmail = '';
  let resendTimer = 0;

  togglePassword.addEventListener('click', () => {
    const visible = passwordInput.type === 'text';
    passwordInput.type = visible ? 'password' : 'text';
    togglePassword.setAttribute('aria-pressed', String(!visible));
    togglePassword.setAttribute('aria-label', visible ? 'Mostrar senha' : 'Ocultar senha');
    passwordInput.focus({preventScroll:true});
  });

  document.querySelectorAll('[data-password-target]').forEach(toggle => {
    const input = document.getElementById(toggle.dataset.passwordTarget);
    toggle.addEventListener('click', () => {
      const visible = input.type === 'text';
      input.type = visible ? 'password' : 'text';
      toggle.setAttribute('aria-pressed', String(!visible));
      const confirmation = input === confirmNewPassword ? 'confirmação da senha' : 'nova senha';
      toggle.setAttribute('aria-label', visible ? `Mostrar ${confirmation}` : `Ocultar ${confirmation}`);
      input.focus({preventScroll:true});
    });
  });

  async function bootstrap() {
    const response = await fetch('/api/security/bootstrap', {credentials:'same-origin', cache:'no-store'});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Não foi possível iniciar a sessão segura.');
    csrf = payload.csrf_token;
    if (payload.authenticated) window.location.replace('/');
  }

  async function authPost(url, body, retried = false) {
    if (!csrf) await bootstrap();
    const response = await fetch(url, {
      method:'POST',
      credentials:'same-origin',
      cache:'no-store',
      headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrf},
      body:JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 403 && payload.code === 'CSRF_REFRESH_REQUIRED' && !retried) {
      csrf = '';
      await bootstrap();
      return authPost(url, body, true);
    }
    if (!response.ok) throw new Error(payload.detail || 'Não foi possível concluir a operação.');
    return payload;
  }

  function setLoginMessage(message = '', success = false) {
    errorBox.textContent = message;
    errorBox.classList.toggle('is-success', !!message && success);
  }

  function setRecoveryError(message = '') {
    recoveryError.textContent = message;
  }

  function showRecoveryStep(step) {
    form.hidden = true;
    recoveryPanel.hidden = false;
    recoveryRequestForm.hidden = step !== 'request';
    recoveryVerifyForm.hidden = step !== 'verify';
    recoveryUpdateForm.hidden = step !== 'update';
    document.getElementById('loginTitle').textContent = 'Recuperar senha';
    document.getElementById('loginIntro').hidden = true;
    document.getElementById('recoveryIntro').textContent = step === 'request'
      ? 'Informe seu e-mail completo para receber um código de recuperação.'
      : step === 'verify'
        ? 'Digite o código de seis dígitos recebido por e-mail.'
        : 'Crie uma nova senha para sua conta.';
    setRecoveryError();
  }

  function clearRecoveryFields() {
    recoveryCode.value = '';
    newPassword.value = '';
    confirmNewPassword.value = '';
    document.querySelectorAll('[data-password-target]').forEach(toggle => {
      const input = document.getElementById(toggle.dataset.passwordTarget);
      input.type = 'password';
      toggle.setAttribute('aria-pressed', 'false');
    });
  }

  function showLogin(message = '', success = false) {
    if (resendTimer) window.clearInterval(resendTimer);
    resendTimer = 0;
    recoveryPanel.hidden = true;
    form.hidden = false;
    document.getElementById('loginTitle').textContent = 'Acesso seguro';
    document.getElementById('loginIntro').hidden = false;
    recoveryMessage.textContent = '';
    setRecoveryError();
    clearRecoveryFields();
    setLoginMessage(message, success);
    emailInput.focus({preventScroll:true});
  }

  function setButtonBusy(target, busy, busyText, normalText) {
    target.disabled = busy;
    target.textContent = busy ? busyText : normalText;
  }

  function startResendCooldown(seconds) {
    if (resendTimer) window.clearInterval(resendTimer);
    let remaining = Math.max(1, Number(seconds) || 60);
    resendRecoveryCode.disabled = true;
    resendRecoveryCode.textContent = `Reenviar código (${remaining}s)`;
    resendTimer = window.setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        window.clearInterval(resendTimer);
        resendTimer = 0;
        resendRecoveryCode.disabled = false;
        resendRecoveryCode.textContent = 'Reenviar código';
      } else {
        resendRecoveryCode.textContent = `Reenviar código (${remaining}s)`;
      }
    }, 1000);
  }

  async function requestRecoveryCode(isResend = false) {
    const sourceEmail = isResend ? requestedRecoveryEmail : recoveryEmail.value.trim().toLowerCase();
    if (!isResend && !recoveryRequestForm.reportValidity()) return;
    const target = isResend ? resendRecoveryCode : sendRecoveryCode;
    let completed = false;
    setRecoveryError();
    setButtonBusy(target, true, isResend ? 'Reenviando...' : 'Enviando...', isResend ? 'Reenviar código' : 'Enviar código');
    try {
      const payload = await authPost('/api/auth/recovery/request', {email:sourceEmail});
      requestedRecoveryEmail = sourceEmail;
      recoveryEmail.value = sourceEmail;
      recoveryCode.value = '';
      showRecoveryStep('verify');
      recoveryMessage.textContent = payload.message;
      startResendCooldown(payload.cooldown_seconds || 60);
      recoveryCode.focus({preventScroll:true});
      completed = true;
    } catch (error) {
      setRecoveryError(String(error && error.message || error));
    } finally {
      if (!completed || !isResend) setButtonBusy(target, false, '', isResend ? 'Reenviar código' : 'Enviar código');
    }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    setLoginMessage();
    setButtonBusy(button, true, 'Entrando...', 'Entrar');
    try {
      await authPost('/api/auth/login', {
        email:emailInput.value.trim().toLowerCase(),
        password:passwordInput.value,
      });
      window.location.replace('/');
    } catch (error) {
      setLoginMessage(String(error && error.message || error));
      csrf = '';
      await bootstrap().catch(() => {});
    } finally {
      passwordInput.value = '';
      setButtonBusy(button, false, '', 'Entrar');
    }
  });

  forgotPassword.addEventListener('click', () => {
    setLoginMessage();
    recoveryEmail.value = emailInput.value.trim().toLowerCase();
    recoveryMessage.textContent = '';
    showRecoveryStep('request');
    recoveryEmail.focus({preventScroll:true});
  });

  recoveryRequestForm.addEventListener('submit', event => {
    event.preventDefault();
    requestRecoveryCode(false);
  });

  resendRecoveryCode.addEventListener('click', () => {
    if (!resendRecoveryCode.disabled) requestRecoveryCode(true);
  });

  recoveryVerifyForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (!recoveryVerifyForm.reportValidity()) return;
    setRecoveryError();
    setButtonBusy(verifyRecoveryCode, true, 'Validando...', 'Validar código');
    try {
      await authPost('/api/auth/recovery/verify', {
        email:requestedRecoveryEmail,
        code:recoveryCode.value.trim(),
      });
      showRecoveryStep('update');
      recoveryMessage.textContent = 'Código confirmado. Defina sua nova senha.';
      newPassword.focus({preventScroll:true});
    } catch (error) {
      setRecoveryError(String(error && error.message || error));
    } finally {
      setButtonBusy(verifyRecoveryCode, false, '', 'Validar código');
    }
  });

  recoveryUpdateForm.addEventListener('submit', async event => {
    event.preventDefault();
    setRecoveryError();
    const password = newPassword.value;
    const confirmation = confirmNewPassword.value;
    if (password !== confirmation) {
      setRecoveryError('As senhas informadas não coincidem.');
      confirmNewPassword.focus({preventScroll:true});
      return;
    }
    if (password.length < 8 || !/\p{L}/u.test(password) || !/[0-9]/.test(password)) {
      setRecoveryError('Use pelo menos 8 caracteres, incluindo uma letra e um número.');
      newPassword.focus({preventScroll:true});
      return;
    }
    setButtonBusy(updateRecoveredPassword, true, 'Atualizando...', 'Atualizar senha');
    try {
      const payload = await authPost('/api/auth/recovery/update', {
        password,
        confirm_password:confirmation,
      });
      emailInput.value = requestedRecoveryEmail;
      requestedRecoveryEmail = '';
      csrf = '';
      await bootstrap().catch(() => {});
      showLogin(payload.message, true);
    } catch (error) {
      setRecoveryError(String(error && error.message || error));
    } finally {
      newPassword.value = '';
      confirmNewPassword.value = '';
      setButtonBusy(updateRecoveredPassword, false, '', 'Atualizar senha');
    }
  });

  backToLogin.addEventListener('click', () => {
    emailInput.value = recoveryEmail.value.trim().toLowerCase() || emailInput.value;
    requestedRecoveryEmail = '';
    showLogin();
  });

  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
  bootstrap().catch(error => { setLoginMessage(String(error && error.message || error)); });
})();
