import os


def pytest_configure(config):
    # LOW-7 NOTE: pytest.ini sets DJANGO_SETTINGS_MODULE = bizal.settings.test
    # which takes effect before this hook runs (ini file is read first).
    # This setdefault is a belt-and-suspenders fallback for environments where
    # pytest.ini is not picked up (e.g. running pytest from a different working
    # directory). It correctly defers to any pre-existing env var so that CI
    # pipelines that explicitly set the variable are not overridden.
    # WARNING: Do not run pytest with DJANGO_SETTINGS_MODULE=bizal.settings.production
    # in your shell environment — the production startup guards will raise
    # ImproperlyConfigured and tests will not run.
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bizal.settings.test')
