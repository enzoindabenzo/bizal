"""
Drop this file in backend/bizal/tests/ (or anywhere pytest already collects
from, e.g. alongside the other app tests). It runs entirely at the AST level
— no Django app registry, no DB — so it's fast and can't be skipped by a
missing migration or a DB that isn't up yet.

Run directly:
    pytest backend/bizal/tests/test_tenant_isolation.py -v

Or as part of the normal suite:
    pytest
"""
import os
import sys

try:
    import pytest
except ImportError:
    # This file is pytest-only (fixtures, bare `assert`, no unittest.TestCase)
    # and is meant to be run via `pytest`, per the module docstring above.
    # It's kept under bizal/tests/ so pytest picks it up automatically
    # alongside the per-app suites, but that same location puts it in the
    # path Django's `manage.py test` discovery (unittest.DiscoverRunner)
    # scans too. pytest isn't a production dependency (see
    # requirements-dev.txt) so it's often not installed when running
    # `python manage.py test` per README's documented workflow — without
    # this guard, that `import pytest` crashed discovery for the *entire*
    # suite with ModuleNotFoundError. unittest's DiscoverRunner only ever
    # collects unittest.TestCase subclasses, and everything below is plain
    # pytest functions/fixtures, so simply not raising here is enough:
    # `manage.py test` imports this module, finds no TestCase in it, and
    # moves on — while `pytest` (with pytest installed) runs it in full.
    pytest = None

_TOOLING_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.abspath(os.path.join(_TOOLING_DIR, "..", ".."))  # <-- points at bizal/backend when this file lives in bizal/backend/bizal/tests/

sys.path.insert(0, _TOOLING_DIR)

from check_tenant_isolation import (  # noqa: E402
    ALLOWLIST, find_view_files, scan_file,
)


def _all_findings():
    files = find_view_files(_BACKEND_DIR)
    findings = []
    for path in files:
        findings.extend(scan_file(path, _BACKEND_DIR))
    return findings


if pytest is not None:
    @pytest.fixture(scope="module")
    def findings():
        return _all_findings()


def test_no_critical_findings_outside_allowlist(findings):
    bad = [f for f in findings if f.category == "CRITICAL" and f.key not in ALLOWLIST]
    assert not bad, (
        "The following views have no tenant-aware permission class AND no "
        "reference to `tenant` anywhere in their body. This usually means "
        "a new view was added using bare IsAuthenticated without scoping "
        "its queryset by request.tenant. Either add a tenant-aware "
        "permission class (tenants.permissions.IsTenantOwner / "
        "IsTenantStaff / HasTenantRole(...) / HasTenantFeature(...) / "
        "TenantDomainOnly), or if it's genuinely self-scoped (only ever "
        "touches request.user), add a justified entry to "
        "tenant_isolation_allowlist.py.\n\n"
        + "\n".join(f"  {b.key}" for b in bad)
    )


def test_no_weak_findings_outside_allowlist(findings):
    bad = [f for f in findings if f.category == "WEAK" and f.key not in ALLOWLIST]
    assert not bad, (
        "The following views use only IsAuthenticated (or no explicit "
        "permission_classes at all) but DO reference `tenant` somewhere in "
        "their body — likely a manual tenant filter that hasn't been "
        "reviewed yet. Review it, then either switch to a tenant-aware "
        "permission class or add a justified allowlist entry.\n\n"
        + "\n".join(f"  {b.key}" for b in bad)
    )


def test_no_unrecognized_permission_classes(findings):
    bad = [f for f in findings if f.category == "UNKNOWN"]
    assert not bad, (
        "The following views use a permission class this checker doesn't "
        "recognize. Either it's a new tenant-aware class that should be "
        "added to TENANT_AWARE_NAMES in check_tenant_isolation.py, or it "
        "needs manual review.\n\n"
        + "\n".join(f"  {b.key} -> {sorted(b.permission_names)}" for b in bad)
    )


def test_allowlist_entries_still_exist(findings):
    """Catches stale allowlist entries — e.g. a view got renamed or deleted
    but its allowlist entry was never cleaned up, silently hiding the fact
    that nothing is actually covering that key anymore."""
    live_keys = {f.key for f in findings}
    stale = [k for k in ALLOWLIST if k not in live_keys]
    assert not stale, (
        "The following tenant_isolation_allowlist.py entries no longer "
        "match any scanned view (renamed, moved, or deleted?). Remove or "
        "update them:\n\n" + "\n".join(f"  {k}" for k in stale)
    )
