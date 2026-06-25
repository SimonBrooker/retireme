from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from datetime import date

from app.extensions import db
from app.models import Account, Inheritance, ADULT_ACCOUNT_TYPES, CURRENCIES, CURRENCY_KEYS

setup_bp = Blueprint("setup", __name__, url_prefix="/setup")


@setup_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile_step():
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
            expenses = request.form.get("annual_expenses_target", "").strip()
            profile.annual_expenses_target = float(expenses) if expenses else None
            currency = request.form.get("currency", "")
            if currency in CURRENCY_KEYS:
                profile.currency = currency
        except (ValueError, KeyError):
            flash("Please enter valid numbers (and a valid date of birth, if given).", "error")
            return render_template(
                "setup_profile.html", profile=profile, currencies=CURRENCIES, hide_sidebar=True, today_iso=date.today().isoformat()
            )

        if profile.retirement_age <= profile.current_age:
            flash("Retirement age must be after your current age.", "error")
            return render_template(
                "setup_profile.html", profile=profile, currencies=CURRENCIES, hide_sidebar=True, today_iso=date.today().isoformat()
            )
        if profile.end_age <= profile.retirement_age:
            flash("Projection end age must be after retirement age.", "error")
            return render_template(
                "setup_profile.html", profile=profile, currencies=CURRENCIES, hide_sidebar=True, today_iso=date.today().isoformat()
            )

        db.session.commit()
        return redirect(url_for("setup.accounts_step"))

    return render_template(
        "setup_profile.html", profile=profile, currencies=CURRENCIES, hide_sidebar=True, today_iso=date.today().isoformat()
    )


@setup_bp.route("/accounts", methods=["GET", "POST"])
@login_required
def accounts_step():
    if request.method == "POST":
        if request.form.get("action") == "delete":
            acc = Account.query.filter_by(
                id=request.form.get("account_id"), user_id=current_user.id
            ).first()
            if acc:
                db.session.delete(acc)
                db.session.commit()
            return redirect(url_for("setup.accounts_step"))

        try:
            acc_type = request.form.get("type", "OTHER")
            is_property = acc_type == "PROPERTY"
            acc = Account(
                user_id=current_user.id,
                name=request.form["name"].strip() or "Untitled account",
                type=acc_type,
                current_balance=float(request.form.get("current_balance") or 0),
                annual_growth_rate=float(request.form.get("annual_growth_rate") or 0),
                annual_contribution=(
                    0.0 if is_property else float(request.form.get("annual_contribution") or 0)
                ),
                contribution_growth_rate=(
                    0.0
                    if is_property
                    else float(request.form.get("contribution_growth_rate") or 0)
                ),
                stop_contributions_at_retirement=bool(
                    request.form.get("stop_contributions_at_retirement")
                ),
                include_in_withdrawal_calc=bool(
                    request.form.get("include_in_withdrawal_calc")
                ),
            )
            db.session.add(acc)
            db.session.commit()
        except ValueError:
            flash("Please enter valid numbers for the account fields.", "error")

        return redirect(url_for("setup.accounts_step"))

    accounts = Account.query.filter_by(user_id=current_user.id).order_by(Account.id).all()
    return render_template(
        "setup_accounts.html", accounts=accounts, account_types=ADULT_ACCOUNT_TYPES, hide_sidebar=True
    )


@setup_bp.route("/inheritances", methods=["GET", "POST"])
@login_required
def inheritances_step():
    accounts = Account.query.filter_by(user_id=current_user.id).order_by(Account.id).all()

    if request.method == "POST":
        if request.form.get("action") == "delete":
            inh = Inheritance.query.filter_by(
                id=request.form.get("inheritance_id"), user_id=current_user.id
            ).first()
            if inh:
                db.session.delete(inh)
                db.session.commit()
            return redirect(url_for("setup.inheritances_step"))

        try:
            target_id = request.form.get("target_account_id") or None
            inh = Inheritance(
                user_id=current_user.id,
                source_name=request.form["source_name"].strip() or "Inheritance",
                expected_age=int(request.form["expected_age"]),
                gross_amount=float(request.form["gross_amount"]),
                share_percent=float(request.form.get("share_percent") or 100),
                target_account_id=int(target_id) if target_id else None,
            )
            db.session.add(inh)
            db.session.commit()
        except (ValueError, KeyError):
            flash("Please fill in the inheritance fields correctly.", "error")

        return redirect(url_for("setup.inheritances_step"))

    inheritances = (
        Inheritance.query.filter_by(user_id=current_user.id)
        .order_by(Inheritance.expected_age)
        .all()
    )
    return render_template(
        "setup_inheritances.html", inheritances=inheritances, accounts=accounts, hide_sidebar=True
    )


@setup_bp.route("/finish")
@login_required
def finish():
    current_user.profile.setup_complete = True
    db.session.commit()
    flash("Setup complete — welcome to your ledger.", "success")
    return redirect(url_for("dashboard.index"))
