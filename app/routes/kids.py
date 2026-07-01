import json
from datetime import date
from dataclasses import replace

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Child, Account, Snapshot
from app.projections import project
from app.routes.history import _AccountWithoutSnapshots

kids_bp = Blueprint("kids", __name__, url_prefix="/kids")


class _ChildProfile:
    """A minimal stand-in for Profile so the existing projection engine can be
    reused as-is for a child's accounts. A child never "retires" within the
    projection horizon, and withdrawal rate isn't a concept that applies here —
    we only ever read total_net_worth back out, never retirement_total."""

    def __init__(self, current_age, end_age):
        self.current_age = current_age
        self.retirement_age = current_age + 1000
        self.end_age = end_age
        self.withdrawal_rate = 0.0


def _project_child(child):
    current_age = child.current_age
    end_age = max(21, current_age + 1)
    return project(_ChildProfile(current_age, end_age), child.accounts, [])


def _build_child_chart_data(child):
    """Recorded-vs-projected chart data per kid account, keyed on the child's
    age — the Kids-page analogue of history._build_chart_data. Returns a dict
    keyed by account id, in the same shape history-charts.js already renders."""
    accounts_with_snaps = [a for a in child.accounts if a.snapshots]
    if not accounts_with_snaps:
        return {}

    current_age = child.current_age
    end_age = max(21, current_age + 1)
    profile = _ChildProfile(current_age, end_age)

    clean_accounts = [_AccountWithoutSnapshots(a) for a in child.accounts]
    clean_rows = project(profile, clean_accounts, [])
    actual_rows = project(profile, child.accounts, [])

    clean_by_age = {r.age: r.balances for r in clean_rows}
    actual_by_age = {r.age: r for r in actual_rows}
    ages = [r.age for r in actual_rows]

    data = {}
    for a in accounts_with_snaps:
        snap_map = {s.age: s.balance for s in a.snapshots}
        data[a.id] = {
            "ages": ages,
            "projected": [
                round((clean_by_age.get(age, {}).get(a.id) or 0), 2) for age in ages
            ],
            "adjusted": [
                round((actual_by_age[age].balances.get(a.id) or 0), 2) for age in ages
            ],
            "actuals": snap_map,
            "current_age": current_age,
        }
    return data


def _show_inflated():
    return request.args.get("inflated") == "1"


def _apply_inflation(rows, child, inflation_rate):
    """Display-only transform — see app/routes/dashboard.py's _apply_inflation
    for the full rationale. No property-equivalent to exclude here, so this
    just scales total_net_worth uniformly from the child's own current age."""
    rate = inflation_rate / 100.0
    return [
        replace(r, total_net_worth=r.total_net_worth * (1 + rate) ** max(0, r.age - child.current_age))
        for r in rows
    ]


@kids_bp.route("/")
@login_required
def index():
    children = Child.query.filter_by(user_id=current_user.id).order_by(Child.id).all()
    inflated = _show_inflated()
    inflation_rate = current_user.profile.inflation_rate

    stats = []
    chart_data = {}
    for child in children:
        rows = _project_child(child)
        if inflated:
            rows = _apply_inflation(rows, child, inflation_rate)
        # rows[0] can be a historical snapshot age once actuals exist, so read
        # the row at the child's actual current age for the "today" figure.
        current_total = next(
            (r.total_net_worth for r in rows if r.age == child.current_age),
            rows[0].total_net_worth,
        )
        row_18 = next((r for r in rows if r.age == 18), None)
        stats.append(
            {
                "child": child,
                "current_total": current_total,
                "at_18": row_18.total_net_worth if row_18 else None,
                "has_accounts": len(child.accounts) > 0,
            }
        )
        chart_data.update(_build_child_chart_data(child))

    return render_template(
        "kids.html",
        children=children,
        stats=stats,
        chart_data_json=json.dumps(chart_data),
        currency_symbol=current_user.profile.currency_symbol,
        today_iso=date.today().isoformat(),
        inflated=inflated,
        inflation_rate=inflation_rate,
    )


@kids_bp.route("/api/projection")
@login_required
def api_projection():
    children = Child.query.filter_by(user_id=current_user.id).order_by(Child.id).all()
    inflated = _show_inflated()
    inflation_rate = current_user.profile.inflation_rate

    per_child_rows = {}
    min_age = max_age = None
    for child in children:
        rows = _project_child(child)
        if inflated:
            rows = _apply_inflation(rows, child, inflation_rate)
        per_child_rows[child.id] = rows
        min_age = rows[0].age if min_age is None else min(min_age, rows[0].age)
        max_age = rows[-1].age if max_age is None else max(max_age, rows[-1].age)

    ages = list(range(min_age, max_age + 1)) if min_age is not None else []

    children_series = []
    for child in children:
        by_age = {r.age: r.total_net_worth for r in per_child_rows[child.id]}
        children_series.append(
            {
                "id": child.id,
                "name": child.name,
                "current_age": child.current_age,
                "balances": [
                    round(by_age[age], 2) if age in by_age else None for age in ages
                ],
            }
        )

    return jsonify(
        {
            "ages": ages,
            "children": children_series,
            "currency_symbol": current_user.profile.currency_symbol,
            "inflated": inflated,
        }
    )


@kids_bp.route("/actual/add", methods=["POST"])
@login_required
def add_actual():
    # Scope to accounts that belong to this user AND to a child (child_id set) —
    # i.e. only junior accounts can get actuals recorded from the Kids page.
    account = (
        Account.query.filter_by(id=request.form.get("account_id"), user_id=current_user.id)
        .filter(Account.child_id.isnot(None))
        .first()
    )
    if not account:
        flash("Choose a child's account.", "error")
        return redirect(url_for("kids.index"))

    try:
        age = int(request.form["age"])
        balance = float(request.form["balance"])
    except (ValueError, KeyError):
        flash("Enter a valid age and balance.", "error")
        return redirect(url_for("kids.index"))

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
    return redirect(url_for("kids.index"))


@kids_bp.route("/actual/<int:snapshot_id>/delete", methods=["POST"])
@login_required
def delete_actual(snapshot_id):
    snap = (
        Snapshot.query.join(Account)
        .filter(Snapshot.id == snapshot_id, Account.user_id == current_user.id)
        .first_or_404()
    )
    db.session.delete(snap)
    db.session.commit()
    flash("Removed.", "success")
    return redirect(url_for("kids.index"))


@kids_bp.route("/add", methods=["POST"])
@login_required
def add_child():
    try:
        name = request.form["name"].strip() or "Untitled"
        dob = date.fromisoformat(request.form["date_of_birth"])
        if dob > date.today():
            raise ValueError("Date of birth can't be in the future.")
        child = Child(user_id=current_user.id, name=name, date_of_birth=dob)
        db.session.add(child)
        db.session.commit()
        flash(f'Added "{child.name}".', "success")
    except (ValueError, KeyError):
        flash("Enter a name and a valid date of birth.", "error")
    return redirect(url_for("kids.index"))


@kids_bp.route("/<int:child_id>/edit", methods=["POST"])
@login_required
def edit_child(child_id):
    child = Child.query.filter_by(id=child_id, user_id=current_user.id).first_or_404()
    try:
        name = request.form["name"].strip() or "Untitled"
        dob = date.fromisoformat(request.form["date_of_birth"])
        if dob > date.today():
            raise ValueError("Date of birth can't be in the future.")
        child.name = name
        child.date_of_birth = dob
        db.session.commit()
        flash(f'Updated "{child.name}".', "success")
    except (ValueError, KeyError):
        db.session.rollback()
        flash("Enter a name and a valid date of birth.", "error")
    return redirect(url_for("kids.index"))


@kids_bp.route("/<int:child_id>/delete", methods=["POST"])
@login_required
def delete_child(child_id):
    child = Child.query.filter_by(id=child_id, user_id=current_user.id).first_or_404()
    name = child.name
    db.session.delete(child)
    db.session.commit()
    flash(f'Removed "{name}" and their accounts.', "success")
    return redirect(url_for("kids.index"))
