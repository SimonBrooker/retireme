from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db, limiter
from app.models import User, Profile
from app.totp_utils import verify_code

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
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
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
        if user and user.check_password(password):
            if user.totp_enabled:
                session["pending_mfa_user_id"] = user.id
                session["pending_mfa_next"] = request.args.get("next") or ""
                return redirect(url_for("auth.verify_mfa"))
            current_app.logger.info(f"Successful login: '{user.username}' from {request.remote_addr}")
            login_user(user)
            next_url = request.args.get("next")
            return redirect(next_url or url_for("dashboard.index"))
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
        code = request.form.get("code", "")
        if verify_code(user.totp_secret, code):
            current_app.logger.info(
                f"Successful MFA verification: '{user.username}' from {request.remote_addr}"
            )
            next_url = session.pop("pending_mfa_next", "") or None
            session.pop("pending_mfa_user_id", None)
            login_user(user)
            return redirect(next_url or url_for("dashboard.index"))
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


@auth_bp.route("/logout")
@login_required
def logout():
    current_app.logger.info(f"Logout: '{current_user.username}' from {request.remote_addr}")
    logout_user()
    return redirect(url_for("auth.login"))
