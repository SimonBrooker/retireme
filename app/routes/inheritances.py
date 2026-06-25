from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Account, Inheritance

inheritances_bp = Blueprint("inheritances", __name__, url_prefix="/inheritances")


def _inheritance_from_form(inh, form):
    target_id = form.get("target_account_id") or None
    inh.source_name = form["source_name"].strip() or "Inheritance"
    inh.expected_age = int(form["expected_age"])
    inh.gross_amount = float(form["gross_amount"])
    inh.share_percent = float(form.get("share_percent") or 100)
    inh.target_account_id = int(target_id) if target_id else None
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


@inheritances_bp.route("/add", methods=["POST"])
@login_required
def add():
    try:
        inh = _inheritance_from_form(Inheritance(user_id=current_user.id), request.form)
        db.session.add(inh)
        db.session.commit()
        flash(f'Added "{inh.source_name}".', "success")
    except (ValueError, KeyError):
        flash("Please fill in the fields correctly.", "error")
    return redirect(url_for("inheritances.index"))


@inheritances_bp.route("/<int:inheritance_id>/edit", methods=["POST"])
@login_required
def edit(inheritance_id):
    inh = Inheritance.query.filter_by(
        id=inheritance_id, user_id=current_user.id
    ).first_or_404()
    try:
        _inheritance_from_form(inh, request.form)
        db.session.commit()
        flash(f'Updated "{inh.source_name}".', "success")
    except (ValueError, KeyError):
        flash("Please fill in the fields correctly.", "error")
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
