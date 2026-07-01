from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Account, Child, ACCOUNT_TYPES, KID_ACCOUNT_TYPES

accounts_bp = Blueprint("accounts", __name__, url_prefix="/accounts")


class AccountFormError(ValueError):
    """Raised for deliberate validation messages we want shown verbatim,
    as opposed to a generic numeric-parsing ValueError."""


def _account_from_form(acc, form):
    acc.name = form["name"].strip() or "Untitled account"
    acc.type = form.get("type", "OTHER")
    acc.current_balance = float(form.get("current_balance") or 0)
    acc.annual_growth_rate = float(form.get("annual_growth_rate") or 0)

    if acc.type == "PROPERTY":
        # Property equity isn't something you make regular contributions into.
        acc.annual_contribution = 0.0
        acc.contribution_growth_rate = 0.0
    else:
        acc.annual_contribution = float(form.get("annual_contribution") or 0)
        acc.contribution_growth_rate = float(form.get("contribution_growth_rate") or 0)

    if acc.type in KID_ACCOUNT_TYPES:
        # Junior accounts belong to a child, not the user — they're never part
        # of the user's own retirement withdrawal calc, and "stop at retirement"
        # is a concept that doesn't apply to a child's account at all.
        acc.include_in_withdrawal_calc = False
        acc.stop_contributions_at_retirement = False
        child_id = form.get("child_id") or None
        if not child_id:
            raise AccountFormError("Select which child this account belongs to.")
        acc.child_id = int(child_id)
    else:
        acc.stop_contributions_at_retirement = bool(form.get("stop_contributions_at_retirement"))
        acc.include_in_withdrawal_calc = bool(form.get("include_in_withdrawal_calc"))
        acc.child_id = None

    acc.notes = (form.get("notes") or "").strip() or None
    return acc


@accounts_bp.route("/")
@login_required
def index():
    accounts = Account.query.filter_by(user_id=current_user.id).order_by(Account.id).all()
    children = Child.query.filter_by(user_id=current_user.id).order_by(Child.id).all()
    return render_template(
        "accounts.html", accounts=accounts, account_types=ACCOUNT_TYPES, children=children
    )


@accounts_bp.route("/new")
@login_required
def new_page():
    children = Child.query.filter_by(user_id=current_user.id).order_by(Child.id).all()
    return render_template(
        "account_form.html", account=None, account_types=ACCOUNT_TYPES, children=children
    )


@accounts_bp.route("/<int:account_id>")
@login_required
def edit_page(account_id):
    acc = Account.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    children = Child.query.filter_by(user_id=current_user.id).order_by(Child.id).all()
    return render_template(
        "account_form.html", account=acc, account_types=ACCOUNT_TYPES, children=children
    )


@accounts_bp.route("/add", methods=["POST"])
@login_required
def add():
    try:
        acc = _account_from_form(Account(user_id=current_user.id), request.form)
        if acc.child_id and not Child.query.filter_by(
            id=acc.child_id, user_id=current_user.id
        ).first():
            raise AccountFormError("That child wasn't found.")
        db.session.add(acc)
        db.session.commit()
        flash(f'Added "{acc.name}".', "success")
    except AccountFormError as e:
        flash(str(e), "error")
        return redirect(url_for("accounts.new_page"))
    except ValueError:
        flash("Please enter valid numbers.", "error")
        return redirect(url_for("accounts.new_page"))
    return redirect(url_for("accounts.index"))


@accounts_bp.route("/<int:account_id>/edit", methods=["POST"])
@login_required
def edit(account_id):
    acc = Account.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    try:
        _account_from_form(acc, request.form)
        if acc.child_id and not Child.query.filter_by(
            id=acc.child_id, user_id=current_user.id
        ).first():
            raise AccountFormError("That child wasn't found.")
        db.session.commit()
        flash(f'Updated "{acc.name}".', "success")
    except AccountFormError as e:
        db.session.rollback()
        flash(str(e), "error")
        return redirect(url_for("accounts.edit_page", account_id=account_id))
    except ValueError:
        db.session.rollback()
        flash("Please enter valid numbers.", "error")
        return redirect(url_for("accounts.edit_page", account_id=account_id))
    return redirect(url_for("accounts.index"))


@accounts_bp.route("/<int:account_id>/delete", methods=["POST"])
@login_required
def delete(account_id):
    acc = Account.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    db.session.delete(acc)
    db.session.commit()
    flash(f'Removed "{acc.name}".', "success")
    return redirect(url_for("accounts.index"))
