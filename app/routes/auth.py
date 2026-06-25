from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash

from app.extensions import db, limiter
from app.models import User, Profile
from app.totp_utils import verify_code

# Dummy hash used when no user is found — ensures the response time is
# indistinguishable from a real failed login, preventing username enumeration.
_DUMMY_HASH = "pbkdf2:sha256:260000$x$" + "a" * 64

MAX_FAILED_ATTEMPTS = 5
MAX_FAILED_MFA_ATTEMPTS = 10
LOCKOUT_DURATION = timedelta(minutes=15)


def _safe_next(url):
    if url and urlparse(url).netloc == "":
        return url
    return None

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/create-account", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def create_account():
    # Only allowed when no account exists yet — this is a single-user app.
    if User.query.first() is not None:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        error = None
        if not username:
            error = "Choose a username."
        elif len(password) < 12:
            error = "Password must be at least 12 characters."
        elif password != confirm:
            error = "Passwords don't match."

        if error:
            flash(error, "error")
            return render_template("create_account.html", username=username)

        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        db.session.add(Profile(user_id=user.id))
        db.session.commit()
        current_app.logger.info(f"Account created: '{user.username}' from {request.remote_addr}")

        login_user(user)
        return redirect(url_for("setup.profile_step"))

    return render_template("create_account.html", username="")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if User.query.first() is None:
        return redirect(url_for("auth.create_account"))
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        now = datetime.now(timezone.utc)

        if user and user.locked_until:
            locked_until = user.locked_until.replace(tzinfo=timezone.utc) if user.locked_until.tzinfo is None else user.locked_until
            if now < locked_until:
                remaining = int((locked_until - now).total_seconds() // 60) + 1
                current_app.logger.warning(
                    f"Login attempt on locked account '{username}' from {request.remote_addr}"
                )
                flash(f"Account locked due to too many failed attempts. Try again in {remaining} minute(s).", "error")
                return render_template("login.html")

        password_correct = user.check_password(password) if user else check_password_hash(_DUMMY_HASH, password)

        if user and password_correct:
            user.failed_login_attempts = 0
            user.failed_mfa_attempts = 0
            user.locked_until = None
            db.session.commit()
            next_param = request.args.get("next") or ""
            # Rotate session to prevent session fixation — preserve only what's
            # needed for the next step before handing control to login_user/MFA.
            session.clear()
            if user.totp_enabled:
                session["pending_mfa_user_id"] = user.id
                session["pending_mfa_next"] = next_param
                return redirect(url_for("auth.verify_mfa"))
            current_app.logger.info(f"Successful login: '{user.username}' from {request.remote_addr}")
            login_user(user)
            next_url = _safe_next(next_param)
            return redirect(next_url or url_for("dashboard.index"))

        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = now + LOCKOUT_DURATION
                db.session.commit()
                current_app.logger.warning(
                    f"Account '{username}' locked after {MAX_FAILED_ATTEMPTS} failed attempts from {request.remote_addr}"
                )
                flash(f"Too many failed attempts — account locked for {int(LOCKOUT_DURATION.total_seconds() // 60)} minutes.", "error")
                return render_template("login.html")
            db.session.commit()

        current_app.logger.warning(
            f"Failed login attempt for username '{username}' from {request.remote_addr}"
        )
        flash("Incorrect username or password.", "error")

    return render_template("login.html")


@auth_bp.route("/login/verify", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def verify_mfa():
    user_id = session.get("pending_mfa_user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    user = User.query.get(user_id)
    if not user or not user.totp_enabled:
        session.pop("pending_mfa_user_id", None)
        session.pop("pending_mfa_next", None)
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        now = datetime.now(timezone.utc)

        # Check if account is locked (may have been locked by MFA failures)
        if user.locked_until:
            locked_until = user.locked_until.replace(tzinfo=timezone.utc) if user.locked_until.tzinfo is None else user.locked_until
            if now < locked_until:
                remaining = int((locked_until - now).total_seconds() // 60) + 1
                session.pop("pending_mfa_user_id", None)
                session.pop("pending_mfa_next", None)
                current_app.logger.warning(
                    f"MFA attempt on locked account '{user.username}' from {request.remote_addr}"
                )
                flash(f"Account locked. Try again in {remaining} minute(s).", "error")
                return redirect(url_for("auth.login"))

        code = request.form.get("code", "")
        if verify_code(user.totp_secret, code):
            user.failed_mfa_attempts = 0
            db.session.commit()
            current_app.logger.info(
                f"Successful MFA verification: '{user.username}' from {request.remote_addr}"
            )
            next_url = _safe_next(session.get("pending_mfa_next") or None)
            session.clear()
            login_user(user)
            return redirect(next_url or url_for("dashboard.index"))

        user.failed_mfa_attempts = (user.failed_mfa_attempts or 0) + 1
        if user.failed_mfa_attempts >= MAX_FAILED_MFA_ATTEMPTS:
            user.locked_until = now + LOCKOUT_DURATION
            user.failed_mfa_attempts = 0
            db.session.commit()
            session.pop("pending_mfa_user_id", None)
            session.pop("pending_mfa_next", None)
            current_app.logger.warning(
                f"Account '{user.username}' locked after {MAX_FAILED_MFA_ATTEMPTS} failed MFA attempts from {request.remote_addr}"
            )
            flash(f"Too many incorrect codes — account locked for {int(LOCKOUT_DURATION.total_seconds() // 60)} minutes.", "error")
            return redirect(url_for("auth.login"))
        db.session.commit()
        current_app.logger.warning(
            f"Failed MFA code for '{user.username}' from {request.remote_addr}"
        )
        flash("Incorrect code — check your authenticator app and try again.", "error")

    return render_template("verify_mfa.html")


@auth_bp.route("/login/cancel")
def cancel_mfa():
    session.pop("pending_mfa_user_id", None)
    session.pop("pending_mfa_next", None)
    return redirect(url_for("auth.login"))


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    current_app.logger.info(f"Logout: '{current_user.username}' from {request.remote_addr}")
    logout_user()
    return redirect(url_for("auth.login"))
