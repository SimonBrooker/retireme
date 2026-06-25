from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Account, Snapshot

history_bp = Blueprint("history", __name__, url_prefix="/history")


@history_bp.route("/")
@login_required
def index():
    accounts = (
        Account.query.filter_by(user_id=current_user.id)
        .order_by(Account.id)
        .all()
    )
    return render_template("history.html", accounts=accounts)


@history_bp.route("/add", methods=["POST"])
@login_required
def add():
    account = Account.query.filter_by(
        id=request.form.get("account_id"), user_id=current_user.id
    ).first()
    if not account:
        flash("Choose an account.", "error")
        return redirect(url_for("history.index"))

    try:
        age = int(request.form["age"])
        balance = float(request.form["balance"])
    except (ValueError, KeyError):
        flash("Enter a valid age and balance.", "error")
        return redirect(url_for("history.index"))

    existing = Snapshot.query.filter_by(account_id=account.id, age=age).first()
    note = (request.form.get("note") or "").strip() or None
    if existing:
        existing.balance = balance
        existing.note = note
        flash(f"Updated {account.name} at age {age}.", "success")
    else:
        db.session.add(Snapshot(account_id=account.id, age=age, balance=balance, note=note))
        flash(f"Recorded {account.name} at age {age}.", "success")
    db.session.commit()
    return redirect(url_for("history.index"))


@history_bp.route("/<int:snapshot_id>/delete", methods=["POST"])
@login_required
def delete(snapshot_id):
    snap = (
        Snapshot.query.join(Account)
        .filter(Snapshot.id == snapshot_id, Account.user_id == current_user.id)
        .first_or_404()
    )
    db.session.delete(snap)
    db.session.commit()
    flash("Removed.", "success")
    return redirect(url_for("history.index"))
