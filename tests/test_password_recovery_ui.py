from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "webapp" / "templates" / "login.html").read_text(encoding="utf-8")
JS = (ROOT / "webapp" / "static" / "login.js").read_text(encoding="utf-8")
CSS = (ROOT / "webapp" / "static" / "login.css").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
GATEWAY = (ROOT / "webapp" / "supabase_gateway.py").read_text(encoding="utf-8")
SESSIONS = (ROOT / "webapp" / "session_store.py").read_text(encoding="utf-8")


def test_login_exposes_recovery_request_without_changing_main_login_fields():
    assert 'id="forgotPassword"' in HTML
    assert "Esqueci minha senha" in HTML
    assert 'id="recoveryEmail"' in HTML
    assert 'type="email" autocomplete="email"' in HTML
    assert "/api/auth/login" in JS
    assert "/api/auth/recovery/request" in JS


def test_recovery_otp_is_six_digit_accessible_and_verified_as_recovery():
    assert 'autocomplete="one-time-code"' in HTML
    assert 'pattern="[0-9]{6}"' in HTML
    assert 'maxlength="6"' in HTML
    assert 'payload={"email": normalized_email, "token": normalized_token, "type": "recovery"}' in GATEWAY
    assert '"/auth/v1/verify"' in GATEWAY


def test_invalid_and_expired_code_message_is_clear_without_internal_detail():
    expected = "Código inválido ou expirado. Solicite um novo código e tente novamente."
    assert expected in MAIN
    assert "otp_expired" not in MAIN


def test_new_password_confirmation_visibility_and_policy_are_present():
    assert 'id="newPassword"' in HTML
    assert 'id="confirmNewPassword"' in HTML
    assert HTML.count('autocomplete="new-password"') == 2
    assert HTML.count('data-password-target=') == 2
    assert "As senhas informadas não coincidem." in JS
    assert "As senhas informadas não coincidem." in MAIN
    assert "pelo menos 8 caracteres" in JS
    assert "pelo menos 8 caracteres" in MAIN


def test_success_updates_through_supabase_and_ends_temporary_recovery_session():
    assert '"PUT",\n                "/auth/v1/user"' in GATEWAY
    assert '"/auth/v1/logout?scope=local"' in GATEWAY
    assert "store.destroy_session(sid)" in MAIN.split('@app.post("/api/auth/recovery/update")', 1)[1].split('@app.post("/api/auth/login")', 1)[0]
    assert "state.wipe_recovery()" in SESSIONS


def test_recovery_token_remains_server_side_and_is_time_limited():
    assert "recovery_access_token: bytearray" in SESSIONS
    assert "RECOVERY_CONTEXT_TTL_SECONDS = 10 * 60" in MAIN
    assert "access_token" not in JS
    assert "access_token" not in HTML


def test_recovery_is_rate_limited_and_client_respects_supabase_interval():
    assert 'limit=1, window_seconds=60' in MAIN
    assert 'limit=3, window_seconds=15 * 60' in MAIN
    assert '"cooldown_seconds": 60' in MAIN
    assert "startResendCooldown(payload.cooldown_seconds || 60)" in JS
    assert "resendRecoveryCode.disabled = true" in JS


def test_no_supabase_secret_is_exposed_in_login_frontend():
    frontend = "\n".join((HTML, JS, CSS))
    assert "SUPABASE_SECRET_KEY" not in frontend
    assert "secret_key" not in frontend
    recovery_gateway = GATEWAY.split("def request_password_recovery", 1)[1].split("def authorize_user", 1)[0]
    assert "self.secret_key" not in recovery_gateway
    assert recovery_gateway.count("api_key=self.publishable_key") == 4
