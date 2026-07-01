import os
import logging
import secrets
import hmac
from datetime import datetime, timezone, timedelta

from flask import Flask, redirect, request, url_for, session, abort
from flask_login import current_user, logout_user
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import db, login_manager, limiter


APP_VERSION = "2.1.0"


def create_app():
    app = Flask(__name__)

    # Trust exactly one reverse proxy hop (nginx) for X-Forwarded-* headers —
    # needed so request.is_secure / generated URLs are correct when TLS is
    # terminated upstream (nginx, behind Cloudflare or otherwise).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    secret_key = os.environ.get("SECRET_KEY", "").strip()
    if not secret_key:
        raise RuntimeError(
            "\n\n"
            "  FATAL: SECRET_KEY environment variable is not set.\n"
            "\n"
            "  Sessions can be forged without a real secret key, which would allow\n"
            "  anyone to authenticate as any user without a password.\n"
            "\n"
            "  Fix: generate a strong random key and set it before starting the app:\n"
            "\n"
            "    python -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "\n"
            "  Then set it in your environment or .env file:\n"
            "\n"
            "    SECRET_KEY=<the value above>\n"
            "\n"
            "  Never reuse the same key across deployments or commit it to git.\n"
        )
    app.config["SECRET_KEY"] = secret_key
    db_path = os.environ.get("DATABASE_PATH", "/data/retirement.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Caps any request body (mainly the data-import upload) to stop a trivial
    # memory-exhaustion DoS via an oversized file.
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

    # Secure cookie flags. SESSION_COOKIE_SECURE is opt-in via env var rather
    # than always-on: plenty of installs run on a home LAN over plain HTTP
    # with no TLS at all (e.g. Unraid without a reverse proxy), and a Secure
    # cookie is silently dropped by the browser over HTTP — that would lock
    # those installs out of login entirely. Set SECURE_COOKIES=true once you
    # have real HTTPS in front of this (nginx + a valid cert, Cloudflare, etc).
    app.config["SESSION_COOKIE_NAME"] = "s"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SECURE_COOKIES", "false").lower() == "true"


    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app.logger.info(f"retireme v{APP_VERSION} starting — if building a new Docker image, ensure APP_VERSION in app/__init__.py and Dockerfile ENV APP_VERSION are both updated.")
    if not app.config["SESSION_COOKIE_SECURE"]:
        app.logger.info(
            "SECURE_COOKIES is not enabled — session cookies will be sent over plain HTTP. "
            "Set SECURE_COOKIES=true once this is served over HTTPS."
        )

    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.routes.auth import auth_bp
    from app.routes.setup import setup_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.accounts import accounts_bp
    from app.routes.inheritances import inheritances_bp
    from app.routes.history import history_bp
    from app.routes.kids import kids_bp
    from app.routes.settings import settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(inheritances_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(kids_bp)
    app.register_blueprint(settings_bp)

    from app.cli import register_cli

    register_cli(app)

    @app.context_processor
    def inject_user():
        return {"current_user": current_user}

    @app.context_processor
    def inject_version():
        return {"app_version": APP_VERSION}

    @app.context_processor
    def inject_theme():
        from app.models import THEME_KEYS
        _legacy_map = {
            "ledger-dark": "dark-indigo",
            "ledger-light": "light-indigo",
            "slate": "dark-blue",
            "meadow": "light-emerald",
        }
        if current_user.is_authenticated and current_user.profile:
            theme = current_user.profile.theme
        else:
            first_user = User.query.first()
            theme = (
                first_user.profile.theme
                if first_user and first_user.profile
                else "dark-indigo"
            )
        if theme not in THEME_KEYS:
            theme = _legacy_map.get(theme, "dark-indigo")
        return {"site_theme": theme}

    @app.context_processor
    def inject_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)
        return {"csrf_token": session["csrf_token"]}

    IDLE_TIMEOUT = timedelta(minutes=30)

    @app.before_request
    def check_session_idle():
        if not current_user.is_authenticated:
            return None
        now = datetime.now(timezone.utc)
        last_active = session.get("last_active")
        if last_active:
            last_active_dt = datetime.fromisoformat(last_active)
            if now - last_active_dt > IDLE_TIMEOUT:
                logout_user()
                session.clear()
                return redirect(url_for("auth.login"))
        session["last_active"] = now.isoformat()
        return None

    @app.before_request
    def csrf_protect():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if request.endpoint in (None, "static"):
                return None
            expected = session.get("csrf_token")
            submitted = request.form.get("csrf_token", "")
            if not expected or not submitted or not hmac.compare_digest(expected, submitted):
                app.logger.warning(
                    f"CSRF check failed for {request.endpoint} from {request.remote_addr}"
                )
                abort(400, description="Your session expired or the form was out of date — please try again.")
        return None

    @app.before_request
    def enforce_app_state():
        if request.endpoint in (None, "static"):
            return None

        if User.query.first() is None:
            if request.endpoint != "auth.create_account":
                return redirect(url_for("auth.create_account"))
            return None

        if current_user.is_authenticated and not current_user.profile.setup_complete:
            allowed = request.endpoint.startswith("setup.") or request.endpoint == "auth.logout"
            if not allowed:
                return redirect(url_for("setup.profile_step"))

        if current_user.is_authenticated and current_user.profile.setup_complete:
            if current_user.profile.sync_age_from_dob():
                db.session.commit()

        return None

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' https://api.github.com; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    with app.app_context():
        db.create_all()
        _ensure_schema()

    return app


def _ensure_schema():
    """
    db.create_all() only creates missing tables — it won't add new columns to a
    table that already exists from an earlier version of the app. This adds any
    columns introduced after the initial release, so upgrading never loses data.
    """
    from sqlalchemy import text

    with db.engine.connect() as conn:
        profile_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(profile)"))}
        if "theme" not in profile_cols:
            conn.execute(
                text("ALTER TABLE profile ADD COLUMN theme VARCHAR(20) DEFAULT 'ledger-dark'")
            )
            conn.commit()
        if "currency" not in profile_cols:
            conn.execute(
                text("ALTER TABLE profile ADD COLUMN currency VARCHAR(3) DEFAULT 'GBP'")
            )
            conn.commit()
        if "date_of_birth" not in profile_cols:
            conn.execute(text("ALTER TABLE profile ADD COLUMN date_of_birth DATE"))
            conn.commit()
        if "inflation_rate" not in profile_cols:
            conn.execute(
                text("ALTER TABLE profile ADD COLUMN inflation_rate FLOAT DEFAULT 3.0")
            )
            conn.commit()

        user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(user)"))}
        if "totp_secret" not in user_cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN totp_secret VARCHAR(32)"))
            conn.commit()
        if "totp_enabled" not in user_cols:
            conn.execute(
                text("ALTER TABLE user ADD COLUMN totp_enabled BOOLEAN DEFAULT 0")
            )
            conn.commit()
        if "failed_login_attempts" not in user_cols:
            conn.execute(
                text("ALTER TABLE user ADD COLUMN failed_login_attempts INTEGER DEFAULT 0")
            )
            conn.commit()
        if "locked_until" not in user_cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN locked_until DATETIME"))
            conn.commit()
        if "pending_totp_secret" not in user_cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN pending_totp_secret VARCHAR(32)"))
            conn.commit()
        if "pending_totp_expires_at" not in user_cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN pending_totp_expires_at DATETIME"))
            conn.commit()
        if "failed_mfa_attempts" not in user_cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN failed_mfa_attempts INTEGER DEFAULT 0"))
            conn.commit()

        account_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(account)"))}
        if "child_id" not in account_cols:
            conn.execute(text("ALTER TABLE account ADD COLUMN child_id INTEGER"))
            conn.commit()

        # Decumulation (and its tax_settings table) has been removed. This is
        # a one-time cleanup for anyone who had it — drops the now-unused
        # table if it's still there from an earlier version; a no-op on any
        # install that never had it (or has already been cleaned up).
        conn.execute(text("DROP TABLE IF EXISTS tax_settings"))
        conn.commit()
