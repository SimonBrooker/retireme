import json

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Account, Snapshot
from app.projections import project

history_bp = Blueprint("history", __name__, url_prefix="/history")


class _AccountWithoutSnapshots:
    """Stand-in for Account with snapshots stripped — used to get the
    'what would the projection have been without any actual data' line."""

    def __init__(self, account):
        self.id = account.id
        self.current_balance = account.current_balance
        self.annual_growth_rate = account.annual_growth_rate
        self.annual_contribution = account.annual_contribution
        self.contribution_growth_rate = account.contribution_growth_rate
        self.stop_contributions_at_retirement = account.stop_contributions_at_retirement
        self.include_in_withdrawal_calc = account.include_in_withdrawal_calc
        self.snapshots = []


def _build_chart_data(profile, accounts, inheritances):
    """For each account that has snapshots, return the data needed to
    draw a 'recorded vs projected' chart: both the original (clean)
    projection and the actual-adjusted projection, plus the recorded dots."""
    accounts_with_snaps = [a for a in accounts if a.snapshots]
    if not accounts_with_snaps:
        return {}

    clean_accounts = [_AccountWithoutSnapshots(a) for a in accounts]
    clean_rows = project(profile, clean_accounts, inheritances)
    actual_rows = project(profile, accounts, inheritances)

    clean_by_age = {r.age: r.balances for r in clean_rows}
    actual_by_age = {r.age: r for r in actual_rows}

    ages = [r.age for r in actual_rows]

    chart_data = {}
    for a in accounts_with_snaps:
        snap_map = {s.age: s.balance for s in a.snapshots}
        chart_data[a.id] = {
            "ages": ages,
            "projected": [
                round((clean_by_age.get(age, {}).get(a.id) or 0), 2) for age in ages
            ],
            "adjusted": [
                round((actual_by_age[age].balances.get(a.id) or 0), 2) for age in ages
            ],
            "actuals": snap_map,
            "current_age": profile.current_age,
        }
    return chart_data


@history_bp.route("/")
@login_required
def index():
    accounts = (
        Account.query.filter_by(user_id=current_user.id)
        .filter(Account.child_id.is_(None))
        .order_by(Account.id)
        .all()
    )
    profile = current_user.profile
    chart_data = _build_chart_data(profile, accounts, current_user.inheritances)
    return render_template(
        "history.html",
        accounts=accounts,
        chart_data_json=json.dumps(chart_data),
        currency_symbol=profile.currency_symbol,
    )


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
