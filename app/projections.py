"""
Pure calculation engine for retirement projections.
Deliberately framework-free so it's easy to unit test.
"""
from dataclasses import dataclass

UNALLOCATED_KEY = "unallocated_inheritance"


@dataclass
class YearRow:
    age: int
    is_retired: bool
    is_historical: bool  # age is before profile.current_age — shown for record only
    balances: dict  # account_id|UNALLOCATED_KEY -> balance (missing key = unknown for that age)
    growth: dict  # account_id -> amount grown this year (None if unknown/overridden)
    contribution: dict  # account_id -> amount contributed this year (None if unknown/overridden)
    is_actual: dict  # account_id -> True if this age's balance came from a recorded Snapshot
    total_net_worth: float  # everything, including property/other excluded accounts
    retirement_total: float  # only accounts flagged "include in withdrawal calc"
    withdrawal_capacity: float  # retirement_total * withdrawal_rate
    inheritance_received_this_year: float = 0.0
    retirement_pct_diff: float = None  # % change in retirement_total vs the previous age's row


def _snapshots_by_account(accounts):
    """Build {account_id: {age: balance}} from each account's snapshots."""
    out = {}
    for a in accounts:
        out[a.id] = {s.age: s.balance for s in a.snapshots}
    return out


def project(profile, accounts, inheritances):
    """
    profile: Profile model instance
    accounts: list[Account] (each may have .snapshots loaded)
    inheritances: list[Inheritance]
    Returns list[YearRow] from min(current_age, earliest recorded snapshot age) to end_age.
    """
    snaps = _snapshots_by_account(accounts)
    eligible_ids = {a.id for a in accounts if a.include_in_withdrawal_calc}

    earliest_snapshot_age = min(
        (age for per_acc in snaps.values() for age in per_acc), default=profile.current_age
    )
    start_age = min(profile.current_age, earliest_snapshot_age)

    inheritances_by_age = {}
    for inh in inheritances:
        inheritances_by_age.setdefault(inh.expected_age, []).append(inh)

    balances = {}  # populated once we reach current_age; before that we only show recorded snapshots
    rows = []
    prev_retirement_total = None

    for age in range(start_age, profile.end_age + 1):
        is_retired = age >= profile.retirement_age
        is_historical = age < profile.current_age
        growth_this_year = {}
        contribution_this_year = {}
        is_actual_this_year = {}
        row_balances = {}

        if is_historical:
            for a in accounts:
                snap_val = snaps.get(a.id, {}).get(age)
                if snap_val is not None:
                    row_balances[a.id] = snap_val
                    is_actual_this_year[a.id] = True

        else:
            if age == profile.current_age:
                # Seed "now" from a recorded snapshot for this exact age if present,
                # otherwise from the account's current balance.
                for a in accounts:
                    snap_val = snaps.get(a.id, {}).get(age)
                    if snap_val is not None:
                        balances[a.id] = snap_val
                        is_actual_this_year[a.id] = True
                    else:
                        balances[a.id] = a.current_balance
                balances[UNALLOCATED_KEY] = 0.0
            else:
                for a in accounts:
                    bal = balances[a.id]
                    growth_amt = bal * (a.annual_growth_rate / 100.0)
                    contributing = not (a.stop_contributions_at_retirement and is_retired)
                    contribution_amt = 0.0
                    if contributing and a.annual_contribution:
                        years_elapsed = age - profile.current_age
                        contribution_amt = a.annual_contribution * (
                            (1 + a.contribution_growth_rate / 100.0) ** years_elapsed
                        )
                    bal = bal + growth_amt + contribution_amt
                    growth_this_year[a.id] = growth_amt
                    contribution_this_year[a.id] = contribution_amt
                    balances[a.id] = bal

                for inh in inheritances_by_age.get(age, []):
                    if inh.target_account_id and inh.target_account_id in balances:
                        balances[inh.target_account_id] += inh.net_amount
                    else:
                        balances[UNALLOCATED_KEY] += inh.net_amount

                # An actual recorded figure always wins over the computed one, and
                # becomes the new anchor that future years compound from.
                for a in accounts:
                    snap_val = snaps.get(a.id, {}).get(age)
                    if snap_val is not None:
                        balances[a.id] = snap_val
                        is_actual_this_year[a.id] = True
                        growth_this_year[a.id] = None
                        contribution_this_year[a.id] = None

            row_balances = dict(balances)

        received_this_year = sum(i.net_amount for i in inheritances_by_age.get(age, []))

        total = sum(row_balances.values())
        retirement_total = sum(v for aid, v in row_balances.items() if aid in eligible_ids)
        withdrawal_capacity = retirement_total * (profile.withdrawal_rate / 100.0)

        if prev_retirement_total:  # None or 0 both mean "no meaningful base to diff against"
            retirement_pct_diff = (
                (retirement_total - prev_retirement_total) / prev_retirement_total
            ) * 100.0
        else:
            retirement_pct_diff = None
        prev_retirement_total = retirement_total

        rows.append(
            YearRow(
                age=age,
                is_retired=is_retired,
                is_historical=is_historical,
                balances=row_balances,
                growth=growth_this_year,
                contribution=contribution_this_year,
                is_actual=is_actual_this_year,
                total_net_worth=total,
                retirement_total=retirement_total,
                withdrawal_capacity=withdrawal_capacity,
                inheritance_received_this_year=received_this_year,
                retirement_pct_diff=retirement_pct_diff,
            )
        )
    return rows
