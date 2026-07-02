from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Account, Inheritance

inheritances_bp = Blueprint("inheritances", __name__, url_prefix="/inheritances")


def _inheritance_from_form(inh, form, user_id):
    from app.models import Account
    target_id = form.get("target_account_id") or None
    inh.source_name = form["source_name"].strip() or "Inheritance"
    inh.expected_age = int(form["expected_age"])
    inh.gross_amount = float(form["gross_amount"])
    inh.share_percent = float(form.get("share_percent") or 100)
    if target_id:
        account = Account.query.filter_by(id=int(target_id), user_id=user_id).first()
        if not account:
            raise ValueError("Invalid target account.")
        inh.target_account_id = account.id
    else:
        inh.target_account_id = None
    inh.notes = (form.get("notes") or "").strip() or None
    return inh


@inheritances_bp.route("/")
@login_required
def index():
    inheritances = (
        Inheritance.query.filter_by(user_id=current_user.id)
        .order_by(Inheritance.expected_age)
        .all()
    )
    accounts = Account.query.filter_by(user_id=current_user.id).order_by(Account.id).all()
    return render_template("inheritances.html", inheritances=inheritances, accounts=accounts)


def _user_accounts():
    return Account.query.filter_by(user_id=current_user.id).order_by(Account.id).all()


@inheritances_bp.route("/new")
@login_required
def new_page():
    return render_template("inheritance_form.html", inheritance=None, accounts=_user_accounts())


@inheritances_bp.route("/<int:inheritance_id>")
@login_required
def edit_page(inheritance_id):
    inh = Inheritance.query.filter_by(id=inheritance_id, user_id=current_user.id).first_or_404()
    return render_template("inheritance_form.html", inheritance=inh, accounts=_user_accounts())


@inheritances_bp.route("/add", methods=["POST"])
@login_required
def add():
    try:
        inh = _inheritance_from_form(Inheritance(user_id=current_user.id), request.form, current_user.id)
        db.session.add(inh)
        db.session.commit()
        flash(f'Added "{inh.source_name}".', "success")
    except (ValueError, KeyError):
        flash("Please fill in the fields correctly.", "error")
        return redirect(url_for("inheritances.new_page"))
    return redirect(url_for("inheritances.index"))


@inheritances_bp.route("/<int:inheritance_id>/edit", methods=["POST"])
@login_required
def edit(inheritance_id):
    inh = Inheritance.query.filter_by(
        id=inheritance_id, user_id=current_user.id
    ).first_or_404()
    try:
        _inheritance_from_form(inh, request.form, current_user.id)
        db.session.commit()
        flash(f'Updated "{inh.source_name}".', "success")
    except (ValueError, KeyError):
        flash("Please fill in the fields correctly.", "error")
        return redirect(url_for("inheritances.edit_page", inheritance_id=inheritance_id))
    return redirect(url_for("inheritances.index"))


@inheritances_bp.route("/<int:inheritance_id>/delete", methods=["POST"])
@login_required
def delete(inheritance_id):
    inh = Inheritance.query.filter_by(
        id=inheritance_id, user_id=current_user.id
    ).first_or_404()
    db.session.delete(inh)
    db.session.commit()
    flash(f'Removed "{inh.source_name}".', "success")
    return redirect(url_for("inheritances.index"))
