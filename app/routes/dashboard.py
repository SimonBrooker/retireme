from dataclasses import replace

from flask import Blueprint, render_template, jsonify, redirect, url_for, request, session
from flask_login import login_required, current_user

from app.projections import project, UNALLOCATED_KEY

dashboard_bp = Blueprint("dashboard", __name__)

SCENARIO_RATES = [3, 5, 7, 9, 12]


def _adult_accounts(user):
    """Everything except junior accounts (JISA/JSIPP) — those belong to
    children, not the user, and are kept out of their net worth/retirement
    figures entirely. They get their own dashboard under Kids.

    Retirement-asset accounts come first, with non-retirement accounts
    (typically property) sorted to the end. A stable sort, so accounts
    within each group keep their existing relative order — only the
    property/non-retirement ones get moved, to the end, as a group. Both
    the "Year by year" table and the "Net worth by account" chart iterate
    this same list in this same order, so fixing it once here covers both."""
    accounts = [a for a in user.accounts if not a.is_kid_account]
    return sorted(accounts, key=lambda a: not a.include_in_withdrawal_calc)


def _show_inflated():
    return bool(session.get("inflated", False))


@dashboard_bp.route("/version")
@login_required
def version():
    """Version + release-history page. The release list is fetched client-side
    from the GitHub API (see releases.js) — same pattern the nav badge already
    uses, and CSP already allows api.github.com."""
    return render_template("version.html")


# The inflation switch only ever appears on the Dashboard and Kids pages, so the
# toggle only needs to return to one of those. Mapping a small whitelist to real
# endpoints means no user-supplied URL ever reaches redirect() — safe by
# construction, no open-redirect surface to validate.
_TOGGLE_DESTS = {"dashboard": "dashboard.index", "kids": "kids.index"}


@dashboard_bp.route("/toggle-inflation", methods=["POST"])
@login_required
def toggle_inflation():
    """Flip the session-backed 'show inflated figures' lens and return to the
    page the switch was toggled from. Display-only — nothing is persisted."""
    session["inflated"] = not session.get("inflated", False)
    dest = url_for(_TOGGLE_DESTS.get(request.form.get("next"), "dashboard.index"))
    return redirect(dest)


def _apply_inflation(rows, accounts, profile):
    """Display-only transform for the "show inflated figures" toggle —
    never touches the underlying growth/contribution modeling, and never
    mutates the rows passed in (those stay in pure today's-money terms,
    used whenever the toggle is off).

    Scales each retirement-eligible account's balance/growth/contribution,
    plus retirement_total and withdrawal_capacity, by
    (1 + inflation_rate)^(years since today) — i.e. "if my actual entered
    growth rate already has inflation backed out, this is roughly what the
    nominal £ figure would say." Property and other non-retirement accounts
    are deliberately left untouched, since their growth rate wasn't
    necessarily discounted the same way — so total_net_worth is recomputed
    as (inflated retirement total + unchanged everything-else), not simply
    scaled, and retirement_pct_diff is recomputed from the inflated
    retirement_total series so the % column stays internally consistent
    with the £ figures next to it. Historical rows (actual recorded past
    data, not a projection) are left exactly as recorded."""
    retirement_ids = {a.id for a in accounts if a.include_in_withdrawal_calc}
    rate = profile.inflation_rate / 100.0

    adjusted = []
    prev_retirement_total = None
    for r in rows:
        if r.is_historical:
            adjusted.append(r)
            prev_retirement_total = r.retirement_total
            continue

        factor = (1 + rate) ** max(0, r.age - profile.current_age)

        new_balances = dict(r.balances)
        new_growth = dict(r.growth)
        new_contribution = dict(r.contribution)
        for aid in retirement_ids:
            if new_balances.get(aid) is not None:
                new_balances[aid] = new_balances[aid] * factor
            if new_growth.get(aid) is not None:
                new_growth[aid] = new_growth[aid] * factor
            if new_contribution.get(aid) is not None:
                new_contribution[aid] = new_contribution[aid] * factor

        new_retirement_total = r.retirement_total * factor
        new_withdrawal_capacity = r.withdrawal_capacity * factor
        non_retirement_total = r.total_net_worth - r.retirement_total
        new_total_net_worth = new_retirement_total + non_retirement_total

        if prev_retirement_total:
            new_pct_diff = (
                (new_retirement_total - prev_retirement_total) / prev_retirement_total * 100.0
            )
        else:
            new_pct_diff = None

        adjusted.append(
            replace(
                r,
                balances=new_balances,
                growth=new_growth,
                contribution=new_contribution,
                retirement_total=new_retirement_total,
                withdrawal_capacity=new_withdrawal_capacity,
                total_net_worth=new_total_net_worth,
                retirement_pct_diff=new_pct_diff,
            )
        )
        prev_retirement_total = new_retirement_total

    return adjusted


class _ScenarioAccount:
    """A read-only stand-in for Account with growth rate overridden to a flat
    hypothetical rate. Contributions, the retirement-asset flag, and recorded
    snapshots are left exactly as configured — only used for the growth-rate
    comparison chart, never persisted."""

    def __init__(self, real_account, growth_rate):
        self.id = real_account.id
        self.current_balance = real_account.current_balance
        self.annual_growth_rate = growth_rate
        self.annual_contribution = real_account.annual_contribution
        self.contribution_growth_rate = real_account.contribution_growth_rate
        self.stop_contributions_at_retirement = real_account.stop_contributions_at_retirement
        self.include_in_withdrawal_calc = real_account.include_in_withdrawal_calc
        self.snapshots = real_account.snapshots


def _growth_scenarios(profile, accounts, inheritances, rows, inflated=False):
    """(ages, series) for the growth-rate comparison chart — today onward,
    retirement assets only (no property), one line per flat rate plus one
    using each account's own configured rate (the main projection, reused).
    When inflated, every line is scaled by the same display-only inflation
    factor used everywhere else on this page, consistent with retirement
    being the only thing this toggle ever touches."""
    ages = [r.age for r in rows if not r.is_historical]
    actual_by_age = {r.age: r.retirement_total for r in rows if not r.is_historical}

    rate_factor = profile.inflation_rate / 100.0
    factors = {a: (1 + rate_factor) ** max(0, a - profile.current_age) for a in ages} if inflated else None

    series = {"actual": [round(actual_by_age[a], 2) for a in ages]}
    for rate in SCENARIO_RATES:
        scenario_accounts = [_ScenarioAccount(a, rate) for a in accounts]
        scenario_rows = project(profile, scenario_accounts, inheritances)
        by_age = {r.age: r.retirement_total for r in scenario_rows}
        if inflated:
            series[str(rate)] = [round(by_age.get(a, 0.0) * factors[a], 2) for a in ages]
        else:
            series[str(rate)] = [round(by_age.get(a, 0.0), 2) for a in ages]

    return ages, series


@dashboard_bp.route("/")
@login_required
def index():
    if not current_user.profile.setup_complete:
        return redirect(url_for("setup.profile_step"))

    profile = current_user.profile
    accounts = _adult_accounts(current_user)
    rows = project(profile, accounts, current_user.inheritances)
    inflated = _show_inflated()
    if inflated:
        rows = _apply_inflation(rows, accounts, profile)

    current_row = next(r for r in rows if r.age == profile.current_age)
    retirement_row = next((r for r in rows if r.age == profile.retirement_age), rows[-1])
    final_row = rows[-1]
    historical_rows = [r for r in rows if r.is_historical]

    return render_template(
        "dashboard.html",
        profile=profile,
        accounts=accounts,
        rows=rows,
        historical_rows=historical_rows,
        current_row=current_row,
        retirement_row=retirement_row,
        final_row=final_row,
        has_accounts=len(accounts) > 0,
        inflated=inflated,
    )


@dashboard_bp.route("/api/projection")
@login_required
def api_projection():
    profile = current_user.profile
    accounts = _adult_accounts(current_user)
    rows = project(profile, accounts, current_user.inheritances)
    inflated = _show_inflated()
    if inflated:
        rows = _apply_inflation(rows, accounts, profile)

    def at(d, key, default=None):
        v = d.get(key, default)
        return round(v, 2) if isinstance(v, (int, float)) else v

    account_series = []
    for a in accounts:
        account_series.append(
            {
                "id": a.id,
                "name": a.name,
                "type": a.type,
                "type_label": a.type_label(),
                "include_in_withdrawal_calc": a.include_in_withdrawal_calc,
                "balances": [at(r.balances, a.id) for r in rows],
                "growth": [at(r.growth, a.id) for r in rows],
                "contribution": [at(r.contribution, a.id) for r in rows],
                "is_actual": [bool(r.is_actual.get(a.id)) for r in rows],
            }
        )

    target_income_age = None
    if profile.annual_expenses_target:
        reached = next(
            (r.age for r in rows if r.withdrawal_capacity >= profile.annual_expenses_target),
            None,
        )
        target_income_age = reached

    scenario_ages, scenario_series = _growth_scenarios(
        profile, accounts, current_user.inheritances, rows, inflated=inflated
    )

    return jsonify(
        {
            "ages": [r.age for r in rows],
            "current_age": profile.current_age,
            "retirement_age": profile.retirement_age,
            "target_income_age": target_income_age,
            "currency_symbol": profile.currency_symbol,
            "currency_code": profile.currency,
            "is_historical": [r.is_historical for r in rows],
            "total_net_worth": [round(r.total_net_worth, 2) for r in rows],
            "retirement_total": [round(r.retirement_total, 2) for r in rows],
            "withdrawal_capacity": [round(r.withdrawal_capacity, 2) for r in rows],
            "inheritance_received": [round(r.inheritance_received_this_year, 2) for r in rows],
            "unallocated_inheritance": [at(r.balances, UNALLOCATED_KEY, 0.0) for r in rows],
            "accounts": account_series,
            "annual_expenses_target": profile.annual_expenses_target,
            "scenario_ages": scenario_ages,
            "scenario_series": scenario_series,
            "scenario_rates": SCENARIO_RATES,
            "inflated": inflated,
        }
    )
