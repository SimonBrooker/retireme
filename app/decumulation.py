"""
Decumulation modeling: what happens after retirement, under different
withdrawal rates, including UK income tax, the State Pension, the pension
access-age lock, and optional inflation modeling.

Deliberately a separate engine from projections.py rather than an extension
of it — the accumulation update rule (grow + contribute) and the decumulation
update rule (grow + maybe contribute + withdraw, then tax the withdrawal) are
different enough that bolting decumulation onto the existing engine would
make both harder to follow. The two meet at one point: decumulation always
starts from the real, accumulated balance the main engine already produced
at retirement age.
"""
from dataclasses import dataclass, replace

# Withdrawing from any of these before tax_settings.pension_access_age isn't
# possible in reality, so the simulation locks them and bridges the gap.
PENSION_LOCKED_TYPES = {"SIPP", "PENSION_DC", "PENSION_DB"}

# Which account types cover a pre-pension-access bridge, and in what order —
# ISA first since it's tax-free and the most natural bridge vehicle, then
# other accessible money. Pension types are never in this list.
BRIDGE_PRIORITY_ORDER = ["ISA", "GIA", "CASH", "OTHER"]

WITHDRAWAL_STRATEGIES = ("fixed", "inflation_adjusted")


def calculate_uk_tax(taxable_income, tax_settings, threshold_scale=1.0):
    """
    Simplified UK income tax: personal allowance (tapered above a threshold,
    losing £1 of allowance per £2 of income over it), then three bands at
    configurable rates and thresholds.

    threshold_scale multiplies every £ threshold (allowance, taper point, and
    both band thresholds) — used to model indexing them with inflation over a
    long retirement. Rates themselves are never scaled, only the cash amounts.
    Leave at 1.0 to model today's policy of frozen thresholds.

    Deliberately not modeled: Scottish income tax bands (different from the
    rest of the UK), National Insurance, and the 25% pension tax-free lump
    sum — this treats the full SIPP/pension withdrawal as taxable, which is
    the more conservative (higher-tax) assumption.
    """
    if taxable_income <= 0:
        return 0.0

    allowance = tax_settings.personal_allowance * threshold_scale
    taper_threshold = tax_settings.personal_allowance_taper_threshold * threshold_scale
    if taxable_income > taper_threshold:
        reduction = (taxable_income - taper_threshold) / 2.0
        allowance = max(0.0, allowance - reduction)

    basic_threshold = tax_settings.basic_rate_threshold * threshold_scale
    higher_threshold = tax_settings.higher_rate_threshold * threshold_scale

    tax = 0.0

    band1_start = allowance
    band1_end = max(band1_start, basic_threshold)
    if taxable_income > band1_start:
        tax += (min(taxable_income, band1_end) - band1_start) * (tax_settings.basic_rate / 100.0)

    band2_start = band1_end
    band2_end = max(band2_start, higher_threshold)
    if taxable_income > band2_start:
        tax += (min(taxable_income, band2_end) - band2_start) * (tax_settings.higher_rate / 100.0)

    band3_start = band2_end
    if taxable_income > band3_start:
        tax += (taxable_income - band3_start) * (tax_settings.additional_rate / 100.0)

    return tax


@dataclass
class DecumulationYear:
    age: int
    balances: dict  # account_id -> balance
    withdrawals: dict  # account_id -> amount actually withdrawn this year
    total_balance: float
    gross_withdrawal: float
    taxable_withdrawal: float
    tax_free_withdrawal: float
    state_pension: float
    taxable_income: float
    tax_due: float
    net_income: float
    depleted: bool
    pension_locked: bool  # True if pension types couldn't be accessed this year
    bridge_shortfall: float  # income that couldn't be met even after bridging


def _bridge_sort_key(account):
    try:
        return BRIDGE_PRIORITY_ORDER.index(account.type)
    except ValueError:
        return len(BRIDGE_PRIORITY_ORDER)


def simulate_decumulation(
    profile,
    accounts,
    tax_settings,
    withdrawal_rate,
    balances_at_retirement,
    withdrawal_strategy="fixed",
    index_tax_thresholds=False,
):
    """
    accounts: retirement-eligible accounts only (no property, no kid accounts) —
        the caller is responsible for that filtering.
    balances_at_retirement: {account_id: balance}, taken from the existing
        accumulation projection at profile.retirement_age.
    withdrawal_rate: a flat % applied to each account's own balance at
        retirement — the classic "safe withdrawal rate" approach, not a % of
        the current balance each year (which can't ever deplete a portfolio
        and so wouldn't show the thing this page exists to show).
    withdrawal_strategy:
        "fixed" — the year-1 withdrawal amount stays flat in nominal terms
            forever (no inflation adjustment at all).
        "inflation_adjusted" — the year-1 amount escalates every year by
            tax_settings.inflation_rate, maintaining constant purchasing
            power. This is the textbook "4% rule" as originally studied.
            The State Pension figure escalates the same way, since it's
            index-linked in reality (a simplified stand-in for the triple
            lock).
    index_tax_thresholds: if True, the personal allowance and all band
        thresholds also scale up with the same inflation factor each year —
        modeling a return to indexed thresholds. If False (the default),
        thresholds stay frozen in nominal terms, matching actual current UK
        policy — which means, realistically, more income drifts into higher
        bands over a long retirement even though nothing "changed." This is
        independent of withdrawal_strategy: indexing thresholds with a fixed
        withdrawal just means tax drifts down over time instead of up.

    If retirement_age is before tax_settings.pension_access_age, pension-type
    accounts are locked for those years — their planned withdrawal is instead
    drawn from non-pension accounts (ISA first), and any amount that still
    can't be covered is reported as that year's bridge_shortfall rather than
    silently understating the income need.

    Returns a list of DecumulationYear from retirement_age to end_age, always
    in nominal (£-at-the-time) terms — use to_todays_money() for a display
    transform into constant purchasing power, which doesn't affect any of
    the underlying math (depletion, tax, locking) here.
    """
    from app.models import TAXABLE_INCOME_ACCOUNT_TYPES

    if withdrawal_strategy not in WITHDRAWAL_STRATEGIES:
        raise ValueError(f"Unknown withdrawal_strategy: {withdrawal_strategy!r}")

    balances = {a.id: balances_at_retirement.get(a.id, 0.0) for a in accounts}
    planned_withdrawal = {a.id: balances[a.id] * (withdrawal_rate / 100.0) for a in accounts}
    bridge_accounts = sorted(
        (a for a in accounts if a.type not in PENSION_LOCKED_TYPES), key=_bridge_sort_key
    )

    years = []
    for age in range(profile.retirement_age, profile.end_age + 1):
        years_elapsed = age - profile.retirement_age
        inflation_factor = (1 + tax_settings.inflation_rate / 100.0) ** years_elapsed

        escalation = inflation_factor if withdrawal_strategy == "inflation_adjusted" else 1.0
        threshold_scale = inflation_factor if index_tax_thresholds else 1.0

        pension_locked = age < tax_settings.pension_access_age

        # Growth/contribution applied first, identically regardless of lock status —
        # a locked pension still grows, it just can't be drawn from yet.
        grown = {}
        for a in accounts:
            bal = balances[a.id]
            growth_amt = bal * (a.annual_growth_rate / 100.0)
            contribution_amt = 0.0
            if not a.stop_contributions_at_retirement and a.annual_contribution:
                contrib_years_elapsed = age - profile.current_age
                contribution_amt = a.annual_contribution * (
                    (1 + a.contribution_growth_rate / 100.0) ** contrib_years_elapsed
                )
            grown[a.id] = bal + growth_amt + contribution_amt

        # Each account's own planned withdrawal (escalated if applicable) —
        # pension accounts get none while locked, with the gap tracked to
        # bridge from elsewhere.
        withdrawal = {}
        locked_shortfall = 0.0
        for a in accounts:
            target = planned_withdrawal[a.id] * escalation
            if a.type in PENSION_LOCKED_TYPES and pension_locked:
                withdrawal[a.id] = 0.0
                locked_shortfall += min(target, max(0.0, grown[a.id]))
            else:
                withdrawal[a.id] = min(target, grown[a.id]) if grown[a.id] > 0 else 0.0

        bridge_shortfall = 0.0
        if locked_shortfall > 0:
            remaining = locked_shortfall
            for a in bridge_accounts:
                if remaining <= 0:
                    break
                headroom = max(0.0, grown[a.id] - withdrawal[a.id])
                if headroom <= 0:
                    continue
                extra = min(headroom, remaining)
                withdrawal[a.id] += extra
                remaining -= extra
            bridge_shortfall = max(0.0, remaining)

        taxable_withdrawal = 0.0
        tax_free_withdrawal = 0.0
        for a in accounts:
            balances[a.id] = max(0.0, grown[a.id] - withdrawal[a.id])
            if a.type in TAXABLE_INCOME_ACCOUNT_TYPES:
                taxable_withdrawal += withdrawal[a.id]
            else:
                tax_free_withdrawal += withdrawal[a.id]

        state_pension_amount = tax_settings.state_pension_annual * escalation
        state_pension = state_pension_amount if age >= tax_settings.state_pension_age else 0.0
        taxable_income = taxable_withdrawal + state_pension
        tax_due = calculate_uk_tax(taxable_income, tax_settings, threshold_scale=threshold_scale)

        total_balance = sum(balances.values())
        gross_withdrawal = taxable_withdrawal + tax_free_withdrawal
        net_income = gross_withdrawal + state_pension - tax_due

        years.append(
            DecumulationYear(
                age=age,
                balances=dict(balances),
                withdrawals=dict(withdrawal),
                total_balance=total_balance,
                gross_withdrawal=gross_withdrawal,
                taxable_withdrawal=taxable_withdrawal,
                tax_free_withdrawal=tax_free_withdrawal,
                state_pension=state_pension,
                taxable_income=taxable_income,
                tax_due=tax_due,
                net_income=net_income,
                depleted=(total_balance <= 0),
                pension_locked=pension_locked,
                bridge_shortfall=bridge_shortfall,
            )
        )

    return years


def to_todays_money(years, profile, inflation_rate):
    """
    Returns a copy of `years` with every money field deflated back to
    constant (retirement-day) purchasing power — a pure display transform.
    Booleans (depleted, pension_locked) and age are untouched; nothing about
    the underlying simulation changes, only how the figures are presented.
    """
    deflated = []
    for y in years:
        factor = (1 + inflation_rate / 100.0) ** (y.age - profile.retirement_age)
        deflated.append(
            replace(
                y,
                balances={k: v / factor for k, v in y.balances.items()},
                withdrawals={k: v / factor for k, v in y.withdrawals.items()},
                total_balance=y.total_balance / factor,
                gross_withdrawal=y.gross_withdrawal / factor,
                taxable_withdrawal=y.taxable_withdrawal / factor,
                tax_free_withdrawal=y.tax_free_withdrawal / factor,
                state_pension=y.state_pension / factor,
                taxable_income=y.taxable_income / factor,
                tax_due=y.tax_due / factor,
                net_income=y.net_income / factor,
                bridge_shortfall=y.bridge_shortfall / factor,
            )
        )
    return deflated


def aggregate_withdrawals_by_type(accounts, years):
    """Returns {account_type: [amount withdrawn that year, ...]} aligned to
    `years`, aggregating multiple accounts of the same type together. Used
    for the "Die with Zero" breakdown chart, where the ask is to see which
    *type* of account is being drawn from each year, not individual accounts."""
    account_type_map = {a.id: a.type for a in accounts}
    types_present = sorted(set(account_type_map.values()))
    by_type = {}
    for t in types_present:
        ids_of_type = {aid for aid, typ in account_type_map.items() if typ == t}
        by_type[t] = [
            round(sum(y.withdrawals.get(aid, 0.0) for aid in ids_of_type), 2) for y in years
        ]
    return by_type


def _amortizing_payment(balance, growth_rate_pct, years):
    """
    The constant per-year withdrawal that exactly depletes `balance` to zero
    after `years` payments, given a constant growth rate — the standard
    annuity-payment formula (the same maths behind a mortgage payment, just
    run in reverse: paying an amount *out* of a balance instead of paying
    one down). Matches this engine's per-year order (grow the balance, then
    subtract the withdrawal) — an "ordinary annuity."

    This is what makes a Die with Zero schedule smooth: the payment is
    calculated once, directly from the growth rate and time horizon, rather
    than approximated by searching for a single flat-rate-of-day-one-balance
    that happens to hit zero somewhere near the end. A flat-rate approach can
    stay basically untouched for decades (while growth keeps pace with the
    fixed withdrawal) and then collapse abruptly in the final years — exactly
    the "flat plateau, then a cliff" shape that doesn't read as a wind-down.
    """
    if years <= 0 or balance <= 0:
        return 0.0
    g = growth_rate_pct / 100.0
    if abs(g) < 1e-9:
        return balance / years
    growth_factor = (1 + g) ** years
    if abs(growth_factor - 1) < 1e-12:
        return balance / years
    return balance * growth_factor * g / (growth_factor - 1)


def simulate_die_with_zero(profile, accounts, tax_settings, balances_at_retirement, index_tax_thresholds=False):
    """
    A smooth, account-by-account amortizing withdrawal schedule that empties
    every retirement account to (almost) exactly zero by end_age — each
    account is independently self-sufficient by construction, rather than
    one flat % applied to every account and solved for in aggregate. That
    means no cross-account bridging is needed here: a pension-locked account
    simply starts its own amortization clock later (at the access age, using
    its balance grown to that point over the shorter remaining window), and
    every account converges on zero at the same final year on its own.

    Deliberately doesn't model contributions continuing into retirement —
    "Die with Zero" is specifically about maximally spending down, which
    doesn't really coexist with also still paying in. Also doesn't currently
    support the inflation-adjusted withdrawal style used elsewhere on the
    page (that needs a growing-annuity payment formula, a real but separate
    piece of work) — this always computes a flat, non-escalating amortizing
    payment. index_tax_thresholds is still honoured, since that only affects
    the tax calculation, not the withdrawal schedule itself.

    Returns a list of DecumulationYear — the same shape simulate_decumulation
    produces, so it's a drop-in for the same chart/table code.
    """
    from app.models import TAXABLE_INCOME_ACCOUNT_TYPES

    balances = {a.id: balances_at_retirement.get(a.id, 0.0) for a in accounts}

    payment = {}
    payment_start_age = {}
    for a in accounts:
        if a.type in PENSION_LOCKED_TYPES and profile.retirement_age < tax_settings.pension_access_age:
            years_locked = tax_settings.pension_access_age - profile.retirement_age
            grown_at_unlock = balances[a.id] * (1 + a.annual_growth_rate / 100.0) ** years_locked
            years_remaining = profile.end_age - tax_settings.pension_access_age + 1
            payment[a.id] = _amortizing_payment(grown_at_unlock, a.annual_growth_rate, years_remaining)
            payment_start_age[a.id] = tax_settings.pension_access_age
        else:
            years_remaining = profile.end_age - profile.retirement_age + 1
            payment[a.id] = _amortizing_payment(balances[a.id], a.annual_growth_rate, years_remaining)
            payment_start_age[a.id] = profile.retirement_age

    years = []
    for age in range(profile.retirement_age, profile.end_age + 1):
        years_elapsed = age - profile.retirement_age
        threshold_scale = (
            (1 + tax_settings.inflation_rate / 100.0) ** years_elapsed if index_tax_thresholds else 1.0
        )

        withdrawal = {}
        for a in accounts:
            bal = balances[a.id]
            grown = bal + bal * (a.annual_growth_rate / 100.0)
            if age >= payment_start_age[a.id]:
                withdrawal[a.id] = min(payment[a.id], grown) if grown > 0 else 0.0
            else:
                withdrawal[a.id] = 0.0
            balances[a.id] = max(0.0, grown - withdrawal[a.id])

        taxable_withdrawal = sum(
            withdrawal[a.id] for a in accounts if a.type in TAXABLE_INCOME_ACCOUNT_TYPES
        )
        tax_free_withdrawal = sum(
            withdrawal[a.id] for a in accounts if a.type not in TAXABLE_INCOME_ACCOUNT_TYPES
        )

        state_pension = (
            tax_settings.state_pension_annual if age >= tax_settings.state_pension_age else 0.0
        )
        taxable_income = taxable_withdrawal + state_pension
        tax_due = calculate_uk_tax(taxable_income, tax_settings, threshold_scale=threshold_scale)

        total_balance = sum(balances.values())
        gross_withdrawal = taxable_withdrawal + tax_free_withdrawal
        net_income = gross_withdrawal + state_pension - tax_due
        pension_locked = age < tax_settings.pension_access_age

        years.append(
            DecumulationYear(
                age=age,
                balances=dict(balances),
                withdrawals=dict(withdrawal),
                total_balance=total_balance,
                gross_withdrawal=gross_withdrawal,
                taxable_withdrawal=taxable_withdrawal,
                tax_free_withdrawal=tax_free_withdrawal,
                state_pension=state_pension,
                taxable_income=taxable_income,
                tax_due=tax_due,
                net_income=net_income,
                depleted=(total_balance <= 0),
                pension_locked=pension_locked,
                bridge_shortfall=0.0,  # no bridging needed — every account is self-sufficient by construction
            )
        )

    return years
