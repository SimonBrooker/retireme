from datetime import datetime, date
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db

ACCOUNT_TYPES = [
    ("CASH", "Cash / savings"),
    ("ISA", "ISA"),
    ("SIPP", "SIPP"),
    ("PENSION_DC", "Workplace pension (DC)"),
    ("PENSION_DB", "Defined benefit pension"),
    ("GIA", "General investment account"),
    ("PROPERTY", "Property equity"),
    ("JISA", "Junior ISA (JISA)"),
    ("JSIPP", "Junior SIPP (JSIPP)"),
    ("OTHER", "Other"),
]
ACCOUNT_TYPE_KEYS = [t[0] for t in ACCOUNT_TYPES]

# Junior accounts belong to a child, not the user — they're kept entirely out
# of the user's own net worth/retirement figures and graphs, not just excluded
# from the withdrawal calc the way property is.
KID_ACCOUNT_TYPES = {"JISA", "JSIPP"}

# What the main setup wizard offers — junior types are excluded since no
# children exist yet at that point in onboarding (added later via Accounts/Kids).
ADULT_ACCOUNT_TYPES = [t for t in ACCOUNT_TYPES if t[0] not in KID_ACCOUNT_TYPES]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    totp_secret = db.Column(db.String(32), nullable=True)
    totp_enabled = db.Column(db.Boolean, default=False, nullable=False)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    pending_totp_secret = db.Column(db.String(32), nullable=True)
    pending_totp_expires_at = db.Column(db.DateTime, nullable=True)

    profile = db.relationship(
        "Profile", backref="user", uselist=False, cascade="all, delete-orphan"
    )
    accounts = db.relationship(
        "Account", backref="user", cascade="all, delete-orphan", order_by="Account.id"
    )
    inheritances = db.relationship(
        "Inheritance",
        backref="user",
        cascade="all, delete-orphan",
        order_by="Inheritance.expected_age",
    )
    children = db.relationship(
        "Child", backref="user", cascade="all, delete-orphan", order_by="Child.id"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


THEMES = [
    ("ledger-dark", "Ledger Dark"),
    ("ledger-light", "Ledger Light"),
    ("slate", "Slate"),
    ("meadow", "Meadow"),
]
THEME_KEYS = [t[0] for t in THEMES]

# (code, name, symbol, flag emoji)
CURRENCIES = [
    ("GBP", "British Pound", "£", "🇬🇧"),
    ("USD", "US Dollar", "$", "🇺🇸"),
    ("EUR", "Euro", "€", "🇪🇺"),
    ("CAD", "Canadian Dollar", "CA$", "🇨🇦"),
    ("AUD", "Australian Dollar", "A$", "🇦🇺"),
]
CURRENCY_KEYS = [c[0] for c in CURRENCIES]
CURRENCY_SYMBOLS = {c[0]: c[2] for c in CURRENCIES}
CURRENCY_FLAGS = {c[0]: c[3] for c in CURRENCIES}
CURRENCY_NAMES = {c[0]: c[1] for c in CURRENCIES}
DEFAULT_CURRENCY = "GBP"  # matches the £ this app always used before currency support existed


def calculate_age(dob: date, today: date = None) -> int:
    """Calendar age (not just a year subtraction) — knocks a year off if this
    year's birthday hasn't happened yet."""
    today = today or date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    current_age = db.Column(db.Integer, nullable=False, default=30)
    date_of_birth = db.Column(db.Date, nullable=True)
    retirement_age = db.Column(db.Integer, nullable=False, default=65)
    end_age = db.Column(db.Integer, nullable=False, default=95)
    withdrawal_rate = db.Column(db.Float, nullable=False, default=4.0)  # %
    # Used only by the optional "show inflated figures" display toggle on the
    # Dashboard/Kids pages — doesn't affect any growth/projection math. Most
    # people who set this have already discounted their entered growth rates
    # by roughly this much, so this is what gets added back for that one view.
    inflation_rate = db.Column(db.Float, nullable=False, default=3.0)  # %
    annual_expenses_target = db.Column(db.Float, nullable=True)
    setup_complete = db.Column(db.Boolean, default=False, nullable=False)
    theme = db.Column(db.String(20), nullable=False, default="ledger-dark")
    currency = db.Column(db.String(3), nullable=False, default=DEFAULT_CURRENCY)

    @property
    def currency_symbol(self) -> str:
        return CURRENCY_SYMBOLS.get(self.currency, CURRENCY_SYMBOLS[DEFAULT_CURRENCY])

    @property
    def currency_flag(self) -> str:
        return CURRENCY_FLAGS.get(self.currency, CURRENCY_FLAGS[DEFAULT_CURRENCY])

    @property
    def currency_name(self) -> str:
        return CURRENCY_NAMES.get(self.currency, CURRENCY_NAMES[DEFAULT_CURRENCY])

    def sync_age_from_dob(self) -> bool:
        """If date_of_birth is set, recompute current_age from it. Returns True
        if current_age actually changed (so the caller knows whether to commit).
        No-op (returns False) if date_of_birth isn't set — current_age then stays
        whatever was typed in manually, exactly as before this feature existed."""
        if not self.date_of_birth:
            return False
        correct_age = calculate_age(self.date_of_birth)
        if correct_age != self.current_age:
            self.current_age = correct_age
            return True
        return False


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    child_id = db.Column(db.Integer, db.ForeignKey("child.id"), nullable=True)

    name = db.Column(db.String(120), nullable=False)
    type = db.Column(db.String(20), nullable=False, default="OTHER")
    current_balance = db.Column(db.Float, nullable=False, default=0.0)
    annual_growth_rate = db.Column(db.Float, nullable=False, default=5.0)  # %
    annual_contribution = db.Column(db.Float, nullable=False, default=0.0)
    contribution_growth_rate = db.Column(db.Float, nullable=False, default=0.0)  # %
    stop_contributions_at_retirement = db.Column(db.Boolean, default=True, nullable=False)
    include_in_withdrawal_calc = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    snapshots = db.relationship(
        "Snapshot", backref="account", cascade="all, delete-orphan", order_by="Snapshot.age"
    )

    def type_label(self) -> str:
        return dict(ACCOUNT_TYPES).get(self.type, self.type)

    @property
    def is_kid_account(self) -> bool:
        return self.type in KID_ACCOUNT_TYPES


class Child(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    name = db.Column(db.String(120), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)

    accounts = db.relationship(
        "Account", backref="child", cascade="all, delete-orphan", order_by="Account.id"
    )

    @property
    def current_age(self) -> int:
        return calculate_age(self.date_of_birth)


class Snapshot(db.Model):
    """An actual, recorded balance for an account at a given age — overrides the
    projected/compounded figure for that age so reality can replace assumptions
    once it's known (e.g. the market did better or worse than your growth rate)."""

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    balance = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(255), nullable=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)


class Inheritance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    source_name = db.Column(db.String(120), nullable=False)
    expected_age = db.Column(db.Integer, nullable=False)
    gross_amount = db.Column(db.Float, nullable=False)
    share_percent = db.Column(db.Float, nullable=False, default=100.0)
    target_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    target_account = db.relationship("Account", foreign_keys=[target_account_id])

    @property
    def net_amount(self) -> float:
        return self.gross_amount * (self.share_percent / 100.0)

