"""
Export/import of a user's financial data (profile, accounts, snapshots, inheritances)
as a single JSON document. Deliberately excludes username/password — this is a data
backup, not a credentials migration, so it's safe to store/share more casually than
the database file itself.
"""
from datetime import datetime, date, timezone

from app.models import ACCOUNT_TYPE_KEYS, CURRENCY_KEYS, DEFAULT_CURRENCY

EXPORT_VERSION = 1

REQUIRED_PROFILE_FIELDS = ["current_age", "retirement_age", "end_age", "withdrawal_rate"]
REQUIRED_ACCOUNT_FIELDS = ["name", "type", "current_balance", "annual_growth_rate"]
REQUIRED_INHERITANCE_FIELDS = ["source_name", "expected_age", "gross_amount"]


def export_user_data(profile, accounts, inheritances, children=None):
    children = children or []
    payload = {
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "current_age": profile.current_age,
            "date_of_birth": profile.date_of_birth.isoformat() if profile.date_of_birth else None,
            "retirement_age": profile.retirement_age,
            "end_age": profile.end_age,
            "withdrawal_rate": profile.withdrawal_rate,
            "annual_expenses_target": profile.annual_expenses_target,
            "theme": profile.theme,
            "currency": profile.currency,
            "setup_complete": profile.setup_complete,
        },
        "children": [
            {"name": c.name, "date_of_birth": c.date_of_birth.isoformat()} for c in children
        ],
        "accounts": [
            {
                "name": a.name,
                "type": a.type,
                "current_balance": a.current_balance,
                "annual_growth_rate": a.annual_growth_rate,
                "annual_contribution": a.annual_contribution,
                "contribution_growth_rate": a.contribution_growth_rate,
                "stop_contributions_at_retirement": a.stop_contributions_at_retirement,
                "include_in_withdrawal_calc": a.include_in_withdrawal_calc,
                "notes": a.notes,
                "child_name": a.child.name if a.child else None,
                "snapshots": [
                    {"age": s.age, "balance": s.balance, "note": s.note} for s in a.snapshots
                ],
            }
            for a in accounts
        ],
        "inheritances": [
            {
                "source_name": i.source_name,
                "expected_age": i.expected_age,
                "gross_amount": i.gross_amount,
                "share_percent": i.share_percent,
                "notes": i.notes,
                "target_account_name": i.target_account.name if i.target_account else None,
            }
            for i in inheritances
        ],
    }
    return payload


class ImportValidationError(ValueError):
    pass


def validate_payload(payload):
    """Raise ImportValidationError with a human-readable message if the file
    doesn't look like a valid retireme export. Returns True if OK."""
    if not isinstance(payload, dict):
        raise ImportValidationError("That file doesn't look like a retireme export (not a JSON object).")

    if "profile" not in payload or not isinstance(payload["profile"], dict):
        raise ImportValidationError("That file doesn't look like a retireme export (missing 'profile').")
    if "accounts" not in payload or not isinstance(payload["accounts"], list):
        raise ImportValidationError("That file doesn't look like a retireme export (missing 'accounts').")

    profile = payload["profile"]
    for field in REQUIRED_PROFILE_FIELDS:
        if field not in profile:
            raise ImportValidationError(f"Profile section is missing required field '{field}'.")

    for idx, acc in enumerate(payload["accounts"]):
        if not isinstance(acc, dict):
            raise ImportValidationError(f"Account #{idx + 1} isn't a valid object.")
        for field in REQUIRED_ACCOUNT_FIELDS:
            if field not in acc:
                raise ImportValidationError(f"Account #{idx + 1} is missing required field '{field}'.")
        if acc["type"] not in ACCOUNT_TYPE_KEYS:
            raise ImportValidationError(
                f"Account \"{acc.get('name', '?')}\" has an unknown type '{acc['type']}'."
            )
        for s_idx, snap in enumerate(acc.get("snapshots", [])):
            if "age" not in snap or "balance" not in snap:
                raise ImportValidationError(
                    f"Snapshot #{s_idx + 1} on account \"{acc.get('name', '?')}\" is missing age/balance."
                )

    for idx, inh in enumerate(payload.get("inheritances", [])):
        if not isinstance(inh, dict):
            raise ImportValidationError(f"Inheritance #{idx + 1} isn't a valid object.")
        for field in REQUIRED_INHERITANCE_FIELDS:
            if field not in inh:
                raise ImportValidationError(f"Inheritance #{idx + 1} is missing required field '{field}'.")

    for idx, child in enumerate(payload.get("children", [])):
        if not isinstance(child, dict):
            raise ImportValidationError(f"Child #{idx + 1} isn't a valid object.")
        if "name" not in child or "date_of_birth" not in child:
            raise ImportValidationError(f"Child #{idx + 1} is missing a name or date of birth.")

    return True


def build_import_objects(payload):
    """
    Pure mapping from a validated payload to transient (unattached) ORM objects.
    Does not touch the database or set user_id/account FKs — the caller persists
    these and links inheritances/kid-accounts to their referenced row once IDs exist.

    Returns (profile_fields: dict, children: list[Child], accounts: list[Account],
             inheritances: list[Inheritance], warnings: list[str])
    Each returned Inheritance has `_target_account_ref` set to the matching transient
    Account (or None). Each kid-type Account has `_child_ref` set to the matching
    transient Child (or None) for the caller to resolve after flush.
    """
    from app.models import Account, Snapshot, Inheritance, Child, KID_ACCOUNT_TYPES  # avoid import cycles

    p = payload["profile"]
    currency = p.get("currency") or DEFAULT_CURRENCY
    if currency not in CURRENCY_KEYS:
        currency = DEFAULT_CURRENCY
    dob_raw = p.get("date_of_birth")
    date_of_birth = date.fromisoformat(dob_raw) if dob_raw else None
    profile_fields = {
        "current_age": int(p["current_age"]),
        "date_of_birth": date_of_birth,
        "retirement_age": int(p["retirement_age"]),
        "end_age": int(p["end_age"]),
        "withdrawal_rate": float(p["withdrawal_rate"]),
        "annual_expenses_target": (
            float(p["annual_expenses_target"]) if p.get("annual_expenses_target") is not None else None
        ),
        "theme": p.get("theme") or "ledger-dark",
        "currency": currency,
        "setup_complete": bool(p.get("setup_complete", True)),
    }

    children = []
    child_name_lookup = {}
    for c in payload.get("children", []):
        child = Child(name=c["name"], date_of_birth=date.fromisoformat(c["date_of_birth"]))
        children.append(child)
        child_name_lookup[c["name"]] = child

    warnings = []

    accounts = []
    name_lookup = {}
    for a in payload.get("accounts", []):
        acc = Account(
            name=a["name"],
            type=a["type"],
            current_balance=float(a["current_balance"]),
            annual_growth_rate=float(a["annual_growth_rate"]),
            annual_contribution=float(a.get("annual_contribution") or 0),
            contribution_growth_rate=float(a.get("contribution_growth_rate") or 0),
            stop_contributions_at_retirement=bool(a.get("stop_contributions_at_retirement", True)),
            include_in_withdrawal_calc=bool(a.get("include_in_withdrawal_calc", True)),
            notes=a.get("notes"),
        )
        if acc.type == "PROPERTY":
            acc.annual_contribution = 0.0
            acc.contribution_growth_rate = 0.0

        acc._child_ref = None
        if acc.type in KID_ACCOUNT_TYPES:
            # Mirrors the form-level rule: junior accounts never count toward the
            # user's own retirement figures, and "stop at retirement" doesn't apply.
            acc.include_in_withdrawal_calc = False
            acc.stop_contributions_at_retirement = False
            child_name = a.get("child_name")
            child_ref = child_name_lookup.get(child_name) if child_name else None
            if child_name and not child_ref:
                warnings.append(
                    f'Account "{a["name"]}" referenced child "{child_name}", which wasn\'t '
                    f"found in the file — left unassigned."
                )
            acc._child_ref = child_ref

        for s in a.get("snapshots", []):
            acc.snapshots.append(
                Snapshot(age=int(s["age"]), balance=float(s["balance"]), note=s.get("note"))
            )
        accounts.append(acc)
        name_lookup[a["name"]] = acc

    inheritances = []
    for i in payload.get("inheritances", []):
        target_name = i.get("target_account_name")
        target_acc = name_lookup.get(target_name) if target_name else None
        if target_name and not target_acc:
            warnings.append(
                f'Inheritance "{i.get("source_name", "?")}" referenced account '
                f'"{target_name}", which wasn\'t found in the file — left unallocated.'
            )
        inh = Inheritance(
            source_name=i["source_name"],
            expected_age=int(i["expected_age"]),
            gross_amount=float(i["gross_amount"]),
            share_percent=float(i.get("share_percent", 100)),
            notes=i.get("notes"),
        )
        inh._target_account_ref = target_acc
        inheritances.append(inh)

    return profile_fields, children, accounts, inheritances, warnings
