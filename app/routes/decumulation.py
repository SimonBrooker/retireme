from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from app.extensions import db
from app.models import TaxSettings
from app.projections import project
from app.decumulation import (
    simulate_decumulation,
    to_todays_money,
    simulate_die_with_zero,
    aggregate_withdrawals_by_type,
)

decumulation_bp = Blueprint("decumulation", __name__, url_prefix="/decumulation")

# Always compared against, alongside whatever rate is set in Settings.
DECUMULATION_RATES = [2, 3, 4, 5, 6]


def _get_or_create_tax_settings(user):
    if user.tax_settings is None:
        ts = TaxSettings(user_id=user.id)
        db.session.add(ts)
        db.session.commit()
    return user.tax_settings


def _retirement_accounts(user):
    """Retirement assets only — no property, no junior (kid) accounts."""
    return [a for a in user.accounts if not a.is_kid_account and a.include_in_withdrawal_calc]


def _comparison_rates(profile):
    return sorted(set(DECUMULATION_RATES) | {round(profile.withdrawal_rate, 2)})


def _view_options():
    """View-only toggles, read from the query string — deliberately not
    persisted, since they're a lens on the data rather than a durable
    assumption (unlike inflation_rate itself, which IS saved)."""
    strategy = request.args.get("strategy", "fixed")
    if strategy not in ("fixed", "inflation_adjusted"):
        strategy = "fixed"
    index_thresholds = request.args.get("index_thresholds", "0") == "1"
    display = request.args.get("display", "nominal")
    if display not in ("nominal", "today"):
        display = "nominal"
    return strategy, index_thresholds, display


def _run_years(profile, accounts, tax_settings, rate, balances, strategy, index_thresholds, display):
    years = simulate_decumulation(
        profile, accounts, tax_settings, rate, balances,
        withdrawal_strategy=strategy, index_tax_thresholds=index_thresholds,
    )
    if display == "today":
        years = to_todays_money(years, profile, tax_settings.inflation_rate)
    return years


def _detail_payload(years):
    return {
        "gross_withdrawal": [round(y.gross_withdrawal, 2) for y in years],
        "tax_free_withdrawal": [round(y.tax_free_withdrawal, 2) for y in years],
        "taxable_withdrawal": [round(y.taxable_withdrawal, 2) for y in years],
        "state_pension": [round(y.state_pension, 2) for y in years],
        "tax_due": [round(y.tax_due, 2) for y in years],
        "net_income": [round(y.net_income, 2) for y in years],
        "taxable_income": [round(y.taxable_income, 2) for y in years],
        "total_balance": [round(y.total_balance, 2) for y in years],
        "pension_locked": [y.pension_locked for y in years],
        "bridge_shortfall": [round(y.bridge_shortfall, 2) for y in years],
    }


@decumulation_bp.route("/")
@login_required
def index():
    profile = current_user.profile
    tax_settings = _get_or_create_tax_settings(current_user)
    accounts = _retirement_accounts(current_user)
    rates = _comparison_rates(profile)
    strategy, index_thresholds, display = _view_options()

    if not accounts:
        return render_template(
            "decumulation.html",
            profile=profile,
            tax_settings=tax_settings,
            has_accounts=False,
            rates=rates,
            strategy=strategy,
            index_thresholds=index_thresholds,
            display=display,
        )

    rows = project(profile, accounts, current_user.inheritances)
    retirement_row = next((r for r in rows if r.age == profile.retirement_age), rows[-1])

    # Depletion/shortfall/locking are facts about the simulation, not the
    # display lens — always computed from the nominal run regardless of
    # whether "today's money" display is requested afterward.
    nominal_years = simulate_decumulation(
        profile, accounts, tax_settings, profile.withdrawal_rate, retirement_row.balances,
        withdrawal_strategy=strategy, index_tax_thresholds=index_thresholds,
    )
    depletion_age = next((y.age for y in nominal_years if y.depleted), None)
    bridge_shortfall_age = next((y.age for y in nominal_years if y.bridge_shortfall > 0), None)
    pension_was_locked = any(y.pension_locked for y in nominal_years)

    dwz_years_nominal = simulate_die_with_zero(
        profile, accounts, tax_settings, retirement_row.balances,
        index_tax_thresholds=index_thresholds,
    ) if accounts and retirement_row.retirement_total > 0 else []
    die_with_zero_first_year = dwz_years_nominal[0] if dwz_years_nominal else None

    display_years = (
        to_todays_money(nominal_years, profile, tax_settings.inflation_rate)
        if display == "today"
        else nominal_years
    )

    return render_template(
        "decumulation.html",
        profile=profile,
        tax_settings=tax_settings,
        has_accounts=True,
        rates=rates,
        retirement_total=retirement_row.retirement_total,
        first_year=display_years[0] if display_years else None,
        depletion_age=depletion_age,
        bridge_shortfall_age=bridge_shortfall_age,
        pension_was_locked=pension_was_locked,
        years=display_years,
        strategy=strategy,
        index_thresholds=index_thresholds,
        display=display,
        die_with_zero_first_year=die_with_zero_first_year,
    )


@decumulation_bp.route("/settings", methods=["POST"])
@login_required
def update_tax_settings():
    ts = _get_or_create_tax_settings(current_user)
    try:
        personal_allowance = float(request.form["personal_allowance"])
        taper_threshold = float(request.form["personal_allowance_taper_threshold"])
        basic_rate = float(request.form["basic_rate"])
        basic_rate_threshold = float(request.form["basic_rate_threshold"])
        higher_rate = float(request.form["higher_rate"])
        higher_rate_threshold = float(request.form["higher_rate_threshold"])
        additional_rate = float(request.form["additional_rate"])
        state_pension_annual = float(request.form["state_pension_annual"])
        state_pension_age = int(request.form["state_pension_age"])
        pension_access_age = int(request.form["pension_access_age"])
        inflation_rate = float(request.form["inflation_rate"])

        if basic_rate_threshold <= 0 or higher_rate_threshold <= basic_rate_threshold:
            raise ValueError("Thresholds must increase: basic < higher.")

        ts.personal_allowance = personal_allowance
        ts.personal_allowance_taper_threshold = taper_threshold
        ts.basic_rate = basic_rate
        ts.basic_rate_threshold = basic_rate_threshold
        ts.higher_rate = higher_rate
        ts.higher_rate_threshold = higher_rate_threshold
        ts.additional_rate = additional_rate
        ts.state_pension_annual = state_pension_annual
        ts.state_pension_age = state_pension_age
        ts.pension_access_age = pension_access_age
        ts.inflation_rate = inflation_rate

        db.session.commit()
        flash("Tax, State Pension, pension-access, and inflation assumptions updated.", "success")
    except (ValueError, KeyError):
        db.session.rollback()
        flash("Please check your numbers — thresholds must increase (basic < higher).", "error")

    return redirect(url_for("decumulation.index"))


@decumulation_bp.route("/api/projection")
@login_required
def api_projection():
    profile = current_user.profile
    tax_settings = _get_or_create_tax_settings(current_user)
    accounts = _retirement_accounts(current_user)
    rates = _comparison_rates(profile)
    strategy, index_thresholds, display = _view_options()

    if not accounts:
        return jsonify(
            {
                "ages": [],
                "scenarios": {},
                "your_rate": profile.withdrawal_rate,
                "currency_symbol": profile.currency_symbol,
                "state_pension_age": tax_settings.state_pension_age,
                "pension_access_age": tax_settings.pension_access_age,
                "detail": None,
                "die_with_zero": None,
            }
        )

    rows = project(profile, accounts, current_user.inheritances)
    retirement_row = next((r for r in rows if r.age == profile.retirement_age), rows[-1])

    ages = list(range(profile.retirement_age, profile.end_age + 1))
    scenarios = {}
    for rate in rates:
        years = _run_years(
            profile, accounts, tax_settings, rate, retirement_row.balances,
            strategy, index_thresholds, display,
        )
        scenarios[str(rate)] = [round(y.total_balance, 2) for y in years]

    detail_years = _run_years(
        profile, accounts, tax_settings, profile.withdrawal_rate, retirement_row.balances,
        strategy, index_thresholds, display,
    )

    dwz_years_nominal = simulate_die_with_zero(
        profile, accounts, tax_settings, retirement_row.balances,
        index_tax_thresholds=index_thresholds,
    )
    dwz_years = (
        to_todays_money(dwz_years_nominal, profile, tax_settings.inflation_rate)
        if display == "today"
        else dwz_years_nominal
    )
    by_type = aggregate_withdrawals_by_type(accounts, dwz_years)
    die_with_zero_payload = {
        "by_type": by_type,
        "state_pension": [round(y.state_pension, 2) for y in dwz_years],
        "total_balance": [round(y.total_balance, 2) for y in dwz_years],
    }

    return jsonify(
        {
            "ages": ages,
            "scenarios": scenarios,
            "your_rate": profile.withdrawal_rate,
            "currency_symbol": profile.currency_symbol,
            "state_pension_age": tax_settings.state_pension_age,
            "pension_access_age": tax_settings.pension_access_age,
            "detail": _detail_payload(detail_years),
            "die_with_zero": die_with_zero_payload,
        }
    )
