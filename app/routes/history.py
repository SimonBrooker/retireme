import json
from datetime import date

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Account, Child, Snapshot, calculate_age
from app.projections import project, ChildProfile

history_bp = Blueprint("history", __name__, url_prefix="/actuals")


def resolve_actual_age(form, dob):
    """Work out the age an actual should be filed under.

    If a `snapshot_date` is supplied and a date of birth is available, derive
    the age from it (returning the date too, for display/export). Otherwise fall
    back to the explicit `age` field. `age` stays the projection engine's key;
    the date is convenience/metadata. Raises ValueError/KeyError on bad input.
    """
    date_raw = (form.get("snapshot_date") or "").strip()
    if date_raw and dob:
        snap_date = date.fromisoformat(date_raw)  # ValueError on bad format
        return calculate_age(dob, snap_date), snap_date
    return int(form["age"]), None  # ValueError/KeyError if age missing/invalid


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


def _chart_entry(a, ages, clean_by_age, actual_by_age, current_age):
    return {
        "ages": ages,
        "projected": [round((clean_by_age.get(age, {}).get(a.id) or 0), 2) for age in ages],
        "adjusted": [round((actual_by_age[age].balances.get(a.id) or 0), 2) for age in ages],
        "actuals": {s.age: s.balance for s in a.snapshots},
        "current_age": current_age,
    }


def _build_chart_data(profile, accounts, inheritances):
    """For each account that has snapshots, the data to draw a 'recorded vs
    projected' chart: the clean projection, the actual-adjusted projection, and
    the recorded dots. Keyed on the owner's age (adult profile here)."""
    accounts_with_snaps = [a for a in accounts if a.snapshots]
    if not accounts_with_snaps:
        return {}

    clean_accounts = [_AccountWithoutSnapshots(a) for a in accounts]
    clean_rows = project(profile, clean_accounts, inheritances)
    actual_rows = project(profile, accounts, inheritances)
    clean_by_age = {r.age: r.balances for r in clean_rows}
    actual_by_age = {r.age: r for r in actual_rows}
    ages = [r.age for r in actual_rows]

    return {a.id: _chart_entry(a, ages, clean_by_age, actual_by_age, profile.current_age)
            for a in accounts_with_snaps}


def _build_child_chart_data(child):
    """Same 'recorded vs projected' data for a child's accounts, but keyed on the
    child's age (the child's projection runs on their own timeline)."""
    accounts_with_snaps = [a for a in child.accounts if a.snapshots]
    if not accounts_with_snaps:
        return {}

    current_age = child.current_age
    profile = ChildProfile(current_age, max(21, current_age + 1))
    clean_accounts = [_AccountWithoutSnapshots(a) for a in child.accounts]
    clean_rows = project(profile, clean_accounts, [])
    actual_rows = project(profile, child.accounts, [])
    clean_by_age = {r.age: r.balances for r in clean_rows}
    actual_by_age = {r.age: r for r in actual_rows}
    ages = [r.age for r in actual_rows]

    return {a.id: _chart_entry(a, ages, clean_by_age, actual_by_age, current_age)
            for a in accounts_with_snaps}


@history_bp.route("/")
@login_required
def index():
    profile = current_user.profile
    adult_accounts = (
        Account.query.filter_by(user_id=current_user.id)
        .filter(Account.child_id.is_(None))
        .order_by(Account.id)
        .all()
    )
    children = Child.query.filter_by(user_id=current_user.id).order_by(Child.id).all()

    chart_data = _build_chart_data(profile, adult_accounts, current_user.inheritances)
    for child in children:
        chart_data.update(_build_child_chart_data(child))

    return render_template(
        "history.html",
        adult_accounts=adult_accounts,
        children=children,
        chart_data_json=json.dumps(chart_data),
        currency_symbol=profile.currency_symbol,
        profile_dob=profile.date_of_birth.isoformat() if profile.date_of_birth else "",
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

    # A kid account's actuals are keyed on the child's age, an adult account's on
    # yours — derive the date→age conversion from whichever owner applies.
    dob = account.child.date_of_birth if account.child else current_user.profile.date_of_birth
    try:
        age, snap_date = resolve_actual_age(request.form, dob)
        balance = float(request.form["balance"])
    except (ValueError, KeyError):
        flash("Enter a valid balance and either a date or an age.", "error")
        return redirect(url_for("history.index"))

    existing = Snapshot.query.filter_by(account_id=account.id, age=age).first()
    note = (request.form.get("note") or "").strip() or None
    if existing:
        existing.balance = balance
        existing.note = note
        existing.snapshot_date = snap_date
        flash(f"Updated {account.name} at age {age}.", "success")
    else:
        db.session.add(
            Snapshot(
                account_id=account.id, age=age, snapshot_date=snap_date, balance=balance, note=note
            )
        )
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
