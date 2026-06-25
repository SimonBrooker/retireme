import json
from datetime import datetime, date, timezone, timedelta

TOTP_SETUP_EXPIRY = timedelta(minutes=10)

from flask import Blueprint, render_template, redirect, url_for, request, flash, Response, current_app
from flask_login import login_required, current_user

from app.extensions import db, limiter
from app.models import THEMES, THEME_KEYS, CURRENCIES, CURRENCY_KEYS
from app.data_io import export_user_data, validate_payload, build_import_objects, ImportValidationError
from app.totp_utils import generate_secret, provisioning_uri, verify_code, generate_qr_svg

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    profile = current_user.profile
    if request.method == "POST":
        try:
            dob_raw = request.form.get("date_of_birth", "").strip()
            if dob_raw:
                profile.date_of_birth = date.fromisoformat(dob_raw)
                profile.sync_age_from_dob()
            else:
                profile.date_of_birth = None
                profile.current_age = int(request.form["current_age"])
            profile.retirement_age = int(request.form["retirement_age"])
            profile.end_age = int(request.form["end_age"])
            profile.withdrawal_rate = float(request.form["withdrawal_rate"])
            profile.inflation_rate = float(request.form["inflation_rate"])
            expenses = request.form.get("annual_expenses_target", "").strip()
            profile.annual_expenses_target = float(expenses) if expenses else None

            if profile.retirement_age <= profile.current_age:
                raise ValueError("retirement_age <= current_age")
            if profile.end_age <= profile.retirement_age:
                raise ValueError("end_age <= retirement_age")

            db.session.commit()
            flash("Settings updated.", "success")
        except (ValueError, KeyError):
            db.session.rollback()
            flash("Check your numbers (and date of birth, if given): current age < retirement age < end age.", "error")
        return redirect(url_for("settings.index"))

    return render_template(
        "settings.html",
        profile=profile,
        themes=THEMES,
        currencies=CURRENCIES,
        today_iso=date.today().isoformat(),
    )


@settings_bp.route("/theme", methods=["POST"])
@login_required
def set_theme():
    theme = request.form.get("theme", "")
    if theme in THEME_KEYS:
        current_user.profile.theme = theme
        db.session.commit()
        flash("Theme updated.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/currency", methods=["POST"])
@login_required
def set_currency():
    currency = request.form.get("currency", "")
    if currency in CURRENCY_KEYS:
        current_user.profile.currency = currency
        db.session.commit()
        flash("Currency updated.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm", "")

    if not current_user.check_password(current_password):
        current_app.logger.warning(f"Failed password-change attempt for '{current_user.username}'")
        flash("Current password is incorrect.", "error")
    elif len(new_password) < 12:
        flash("New password must be at least 12 characters.", "error")
    elif new_password != confirm:
        flash("New passwords don't match.", "error")
    else:
        current_user.set_password(new_password)
        db.session.commit()
        current_app.logger.info(f"Password changed for '{current_user.username}'")
        flash("Password changed.", "success")

    return redirect(url_for("settings.index"))


@settings_bp.route("/mfa/setup", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute")
def mfa_setup():
    if current_user.totp_enabled:
        flash("Two-factor authentication is already enabled.", "error")
        return redirect(url_for("settings.index"))

    now = datetime.now(timezone.utc)

    if request.method == "POST":
        expires = current_user.pending_totp_expires_at
        if expires:
            expires = expires.replace(tzinfo=timezone.utc) if expires.tzinfo is None else expires
        secret = current_user.pending_totp_secret if (expires and now < expires) else None
        code = request.form.get("code", "")
        if not secret:
            flash("That setup session expired — scan the new code below.", "error")
        elif verify_code(secret, code):
            current_user.totp_secret = secret
            current_user.totp_enabled = True
            current_user.pending_totp_secret = None
            current_user.pending_totp_expires_at = None
            db.session.commit()
            current_app.logger.info(f"Two-factor authentication enabled for '{current_user.username}'")
            flash("Two-factor authentication is now enabled.", "success")
            return redirect(url_for("settings.index"))
        else:
            flash("That code didn't match — check your app and try again.", "error")

    # Keep the same pending secret across a failed attempt so the QR the
    # person already scanned is still valid; only generate a fresh one if
    # there's no setup in progress or the previous one expired.
    expires = current_user.pending_totp_expires_at
    if expires:
        expires = expires.replace(tzinfo=timezone.utc) if expires.tzinfo is None else expires
    if not current_user.pending_totp_secret or not expires or now >= expires:
        current_user.pending_totp_secret = generate_secret()
        current_user.pending_totp_expires_at = now + TOTP_SETUP_EXPIRY
        db.session.commit()
    secret = current_user.pending_totp_secret

    uri = provisioning_uri(secret, current_user.username)
    qr_svg = generate_qr_svg(uri)

    return render_template("mfa_setup.html", secret=secret, qr_svg=qr_svg)


@settings_bp.route("/mfa/cancel-setup", methods=["POST"])
@login_required
def mfa_cancel_setup():
    current_user.pending_totp_secret = None
    current_user.pending_totp_expires_at = None
    db.session.commit()
    return redirect(url_for("settings.index"))


@settings_bp.route("/mfa/disable", methods=["POST"])
@login_required
def mfa_disable():
    password = request.form.get("password", "")
    if not current_user.check_password(password):
        flash("Incorrect password.", "error")
    else:
        current_user.totp_enabled = False
        current_user.totp_secret = None
        db.session.commit()
        current_app.logger.info(f"Two-factor authentication disabled for '{current_user.username}'")
        flash("Two-factor authentication disabled.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/export")
@login_required
def export_data():
    current_app.logger.info(f"Data export by '{current_user.username}' from {request.remote_addr}")
    payload = export_user_data(
        current_user.profile,
        current_user.accounts,
        current_user.inheritances,
        current_user.children,
    )
    body = json.dumps(payload, indent=2)
    filename = f"retireme-export-{datetime.now(timezone.utc).date().isoformat()}.json"
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@settings_bp.route("/import", methods=["POST"])
@login_required
def import_data():
    if not request.form.get("confirm_import"):
        flash("Please tick the confirmation box before importing.", "error")
        return redirect(url_for("settings.index"))

    file = request.files.get("file")
    if not file or file.filename == "":
        flash("Choose a file to import.", "error")
        return redirect(url_for("settings.index"))

    try:
        payload = json.load(file.stream)
        validate_payload(payload)
        profile_fields, new_children, new_accounts, new_inheritances, warnings = build_import_objects(payload)
    except (ImportValidationError, ValueError, TypeError, KeyError, json.JSONDecodeError) as e:
        flash(f"Import failed: {e}", "error")
        return redirect(url_for("settings.index"))

    # Delete via ORM (not a bulk query.delete()) so the Account -> Snapshot and
    # Child -> Account cascades actually fire and nothing gets left orphaned.
    for acc in list(current_user.accounts):
        db.session.delete(acc)
    for inh in list(current_user.inheritances):
        db.session.delete(inh)
    for child in list(current_user.children):
        db.session.delete(child)
    db.session.flush()

    for field, value in profile_fields.items():
        setattr(current_user.profile, field, value)

    for child in new_children:
        child.user_id = current_user.id
        db.session.add(child)
    db.session.flush()  # new children need IDs before kid-accounts can link to them

    for acc in new_accounts:
        acc.user_id = current_user.id
        child_ref = getattr(acc, "_child_ref", None)
        acc.child_id = child_ref.id if child_ref else None
        db.session.add(acc)
    db.session.flush()  # new accounts need IDs before inheritances can link to them

    for inh in new_inheritances:
        inh.user_id = current_user.id
        target = getattr(inh, "_target_account_ref", None)
        inh.target_account_id = target.id if target else None
        db.session.add(inh)

    db.session.commit()
    current_app.logger.info(
        f"Data import by '{current_user.username}' from {request.remote_addr}: "
        f"{len(new_children)} child(ren), {len(new_accounts)} account(s), {len(new_inheritances)} inheritance(s)"
    )

    plural = "y" if len(new_inheritances) == 1 else "ies"
    flash(
        f"Import complete: {len(new_children)} child(ren), {len(new_accounts)} account(s), "
        f"{len(new_inheritances)} inheritance entr{plural} restored.",
        "success",
    )
    for w in warnings:
        flash(w, "error")
    return redirect(url_for("dashboard.index"))


@settings_bp.route("/reset", methods=["POST"])
@login_required
def reset_data():
    if request.form.get("confirm_reset", "").strip() != "RESET":
        flash("Type RESET exactly (all caps) to confirm.", "error")
        return redirect(url_for("settings.index"))

    for acc in list(current_user.accounts):
        db.session.delete(acc)
    for inh in list(current_user.inheritances):
        db.session.delete(inh)
    for child in list(current_user.children):
        db.session.delete(child)

    profile = current_user.profile
    profile.current_age = 30
    profile.date_of_birth = None
    profile.retirement_age = 65
    profile.end_age = 95
    profile.withdrawal_rate = 4.0
    profile.inflation_rate = 3.0
    profile.annual_expenses_target = None
    profile.setup_complete = False

    db.session.commit()
    current_app.logger.warning(
        f"Full data reset performed by '{current_user.username}' from {request.remote_addr}"
    )
    flash("All accounts, children, inheritance entries, and history have been cleared.", "success")
    return redirect(url_for("setup.profile_step"))
