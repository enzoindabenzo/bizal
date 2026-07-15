"""
Dedicated token generator for the email-verification flow.

H-1 FIX: Previously, both the password-reset flow and the email-verification
flow used Django's shared `default_token_generator`
(django.contrib.auth.tokens.PasswordResetTokenGenerator). Because the token
hash only depends on (user.pk, user.password, user.last_login, timestamp) —
nothing that identifies *which* flow minted it — a token issued for one
purpose was cryptographically valid for the other endpoint too. A
password-reset email landing in an attacker's inbox (e.g. a shared mailbox,
or a user who requested a reset for an unrelated reason) could be replayed
against /api/auth/verify-email/<uid>/<token>/ to mark the account as
verified, and vice versa.

EmailVerificationTokenGenerator mixes a fixed, purpose-specific string into
the hash input so a token minted by one generator is never accepted by the
other, even for the same user/password/timestamp. Use
`email_verification_token_generator` for every verification
make_token()/check_token() call; reserve `default_token_generator` for the
password-reset pair only.
"""
from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        return f"email-verify-{super()._make_hash_value(user, timestamp)}"


email_verification_token_generator = EmailVerificationTokenGenerator()
