"""
Thin wrapper around pyotp/qrcode for TOTP-based login MFA.

Isolating the library calls here means:
- the rest of the app doesn't need to know pyotp/qrcode's exact APIs
- a broken or missing QR renderer never blocks 2FA setup — manual key entry
  into an authenticator app always works as a fallback, regardless
"""
import io

import pyotp

ISSUER = "retireme"


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    """The otpauth:// URI an authenticator app reads from the QR code."""
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def verify_code(secret: str, code: str) -> bool:
    """valid_window=1 tolerates the code from one step before/after now (±30s),
    which absorbs ordinary clock drift between the server and the phone."""
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False


def generate_qr_svg(data: str):
    """Returns inline SVG markup, or None if QR generation isn't available for
    any reason (dependency missing, render failure, etc.) — callers should fall
    back to showing the secret for manual entry, which always works regardless
    of whether this succeeds."""
    try:
        import qrcode
        import qrcode.image.svg

        img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")
    except Exception:
        return None
