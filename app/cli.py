"""
flask reset-password — run via `docker exec -it <container> flask reset-password`.

This is the account-recovery backstop: it needs server/container access rather
than your old password or a working authenticator app, which makes it the one
path that can never lock you out completely. Resetting also clears any 2FA,
since if you're locked out you may have lost your authenticator device too —
you can re-enable it from Settings after logging back in.
"""
import click

from app.extensions import db
from app.models import User


def register_cli(app):
    @app.cli.command("reset-password")
    @click.argument("username", required=False)
    def reset_password(username):
        users = User.query.all()
        if not users:
            click.echo("No account exists yet — nothing to reset.")
            return

        if username:
            user = User.query.filter_by(username=username).first()
            if not user:
                names = ", ".join(u.username for u in users)
                click.echo(f"No user named '{username}'. Existing users: {names}")
                return
        elif len(users) == 1:
            user = users[0]
        else:
            names = ", ".join(u.username for u in users)
            click.echo("Multiple users exist — specify one: flask reset-password <username>")
            click.echo(f"Existing usernames: {names}")
            return

        click.echo(f"Resetting credentials for '{user.username}'.")
        new_password = click.prompt("New password", hide_input=True, confirmation_prompt=True)
        if len(new_password) < 12:
            click.echo("Password must be at least 12 characters. Aborted.")
            return

        user.set_password(new_password)
        if user.totp_enabled or user.totp_secret:
            user.totp_enabled = False
            user.totp_secret = None
            click.echo("Two-factor authentication has also been cleared — re-enable it from Settings after logging in, if you'd like.")

        db.session.commit()
        click.echo("Done — password updated.")
