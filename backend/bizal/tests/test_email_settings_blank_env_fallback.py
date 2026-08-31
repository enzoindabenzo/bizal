import importlib
import os

from django.test import SimpleTestCase


class BlankEnvEmailFallbackTest(SimpleTestCase):
    """
    REGRESSION: .env (copied from .env.example, which ships these blank for
    the operator to fill in) sets DEFAULT_FROM_EMAIL='' and ADMIN_EMAIL=''.
    python-dotenv loads that as an empty-but-present env var, so
    os.environ.get(key, default) never falls back to the intended default —
    the key IS set, just to ''. That silently sent every admin-notification
    send_mail() call (e.g. contact.views.PlatformContactCreateView) with
    recipient_list=[''], which mail backends drop without error or
    exception: nothing in mail.outbox, nothing printed by the console
    backend, no crash. bizal/settings/base.py now uses `or` instead of a
    dict-style default for these two settings specifically, so a blank env
    var falls back the same as a fully-unset one.
    """

    def _reload_base_settings_with_env(self, env_overrides):
        from bizal.settings import base as base_settings

        old_environ = dict(os.environ)
        try:
            os.environ.update(env_overrides)
            reloaded = importlib.reload(base_settings)
            return reloaded.DEFAULT_FROM_EMAIL, reloaded.ADMIN_EMAIL
        finally:
            os.environ.clear()
            os.environ.update(old_environ)
            importlib.reload(base_settings)  # restore normal state

    def test_blank_env_values_fall_back_to_defaults(self):
        default_from, admin_email = self._reload_base_settings_with_env({
            'DEFAULT_FROM_EMAIL': '', 'ADMIN_EMAIL': '',
        })
        self.assertEqual(default_from, 'noreply@bizal.al')
        self.assertEqual(admin_email, 'admin@bizal.al')

    def test_unset_env_values_fall_back_to_defaults(self):
        old_environ = dict(os.environ)
        os.environ.pop('DEFAULT_FROM_EMAIL', None)
        os.environ.pop('ADMIN_EMAIL', None)
        try:
            from bizal.settings import base as base_settings
            reloaded = importlib.reload(base_settings)
            self.assertEqual(reloaded.DEFAULT_FROM_EMAIL, 'noreply@bizal.al')
            self.assertEqual(reloaded.ADMIN_EMAIL, 'admin@bizal.al')
        finally:
            os.environ.clear()
            os.environ.update(old_environ)
            importlib.reload(base_settings)

    def test_real_env_values_are_still_respected(self):
        default_from, admin_email = self._reload_base_settings_with_env({
            'DEFAULT_FROM_EMAIL': 'hello@example.com', 'ADMIN_EMAIL': 'staff@example.com',
        })
        self.assertEqual(default_from, 'hello@example.com')
        self.assertEqual(admin_email, 'staff@example.com')