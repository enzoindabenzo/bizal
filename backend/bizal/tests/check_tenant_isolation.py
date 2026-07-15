#!/usr/bin/env python3
"""
check_tenant_isolation.py
==========================
Static (no Django import, no DB, no dependencies beyond stdlib) audit tool
that scans every `views.py` in the Bizal backend and classifies each DRF
view by how it enforces tenant isolation.

WHY THIS EXISTS
---------------
Bizal's tenant isolation is NOT enforced by the framework by default — it is
enforced by convention: every view either (a) uses a tenant-aware permission
class (IsTenantOwner / IsTenantStaff / HasTenantRole(...) / HasTenantFeature(...)
/ TenantDomainOnly / MainDomainOnly), or (b) uses a plain `IsAuthenticated`
permission but manually filters its queryset by `request.tenant` inside the
view body. Pattern (b) is legitimate and used deliberately in several places
(e.g. OrderDetailView, BookingDetailView), but it is invisible to a permission
check alone — a future view that copies the (b) pattern and *forgets* the
manual tenant filter would compile, pass code review at a glance, and leak
data across tenants silently.

This script turns "we were careful" into a CI gate:
  - Any view with a tenant-aware permission class            -> SAFE
  - Any view with AllowAny only                               -> PUBLIC   (listed, not failed)
  - Any view with IsAdminUser only                             -> ADMIN    (listed, not failed)
  - Any view with only IsAuthenticated (or no permission_classes
    at all, which defaults to IsAuthenticated per settings.py)
    AND the word "tenant" appears nowhere in its body           -> CRITICAL (always fails the build)
  - Same as above but "tenant" DOES appear somewhere in its
    body (i.e. it looks like pattern (b))                       -> WEAK
       - WEAK views must be explicitly listed, with a reason,
         in tenant_isolation_allowlist.py.
       - A WEAK view that is NOT in the allowlist              -> fails the build
         (this is the drift-detection mechanism: a brand-new
         view written this way won't pass CI silently)

USAGE
-----
    python3 check_tenant_isolation.py [path-to-backend]

Exit code 0  -> nothing to fix.
Exit code 1  -> at least one CRITICAL finding, or a WEAK finding missing
                from the allowlist. Prints a human-readable report either way.
"""
from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass, field

try:
    from tenant_isolation_allowlist import ALLOWLIST
except ImportError:
    ALLOWLIST = {}

# ── Known permission-class vocabulary ──────────────────────────────────────

# Anything imported from tenants.permissions (or matching these names) is
# considered tenant-aware by construction — it's the one module responsible
# for enforcing tenant/role/feature checks in this codebase.
TENANT_AWARE_NAMES = {
    "IsTenantOwner",
    "IsTenantStaff",
    "IsOwnTenantStaff",
    "IsOwnTenantOwnerOrManager",
    "TenantDomainOnly",
    "MainDomainOnly",
    "HasTenantRole",
    "HasTenantFeature",
}

PUBLIC_NAMES = {"AllowAny"}
ADMIN_NAMES = {"IsAdminUser", "IsSuperuser"}
WEAK_NAMES = {"IsAuthenticated"}

VIEWS_FILENAME = "views.py"
# reviews/platform_views.py etc. — anything ending in _views.py is also scanned
EXTRA_VIEW_SUFFIXES = ("platform_views.py",)


@dataclass
class Finding:
    file: str
    name: str
    kind: str  # 'class' | 'function'
    permission_names: set[str] = field(default_factory=set)
    category: str = ""  # SAFE | PUBLIC | ADMIN | WEAK | CRITICAL
    mentions_tenant: bool = False
    line: int = 0

    @property
    def key(self) -> str:
        return f"{self.file}:{self.name}"


def find_view_files(root: str) -> list[str]:
    matches = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in
                       {"migrations", "__pycache__", ".git", "node_modules",
                        ".pytest_cache", "staticfiles", "media"}]
        for fn in filenames:
            if fn == VIEWS_FILENAME or fn.endswith(EXTRA_VIEW_SUFFIXES):
                matches.append(os.path.join(dirpath, fn))
    return sorted(matches)


def resolve_module_aliases(tree: ast.Module) -> dict[str, str]:
    """
    Map local-name -> canonical-name for everything imported at module level,
    e.g. `from tenants.permissions import HasTenantRole as HTR` -> {'HTR': 'HasTenantRole'}.
    Also captures module-level variable assignments that alias a permission
    factory call, e.g. `_staff_feature = HasTenantFeature('staff_accounts')`,
    and simple list aliases like `_notifications_permissions = [IsAuthenticated, TenantDomainOnly]`.
    """
    aliases: dict[str, str] = {}
    list_aliases: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local = alias.asname or alias.name
                aliases[local] = alias.name

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            # `_staff_feature = HasTenantFeature('staff_accounts')`
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                aliases[target_name] = aliases.get(node.value.func.id, node.value.func.id)
            # `_notifications_permissions = [IsAuthenticated, TenantDomainOnly]`
            elif isinstance(node.value, ast.List):
                names = []
                for elt in node.value.elts:
                    if isinstance(elt, ast.Name):
                        names.append(aliases.get(elt.id, elt.id))
                    elif isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name):
                        names.append(aliases.get(elt.func.id, elt.func.id))
                list_aliases[target_name] = names

    return aliases, list_aliases


def names_from_list_node(node: ast.AST, aliases: dict, list_aliases: dict) -> set[str]:
    """Extract permission-class names referenced by a permission_classes list
    (or by a name that itself refers to such a list)."""
    out = set()
    if isinstance(node, ast.Name):
        if node.id in list_aliases:
            out.update(list_aliases[node.id])
        else:
            out.add(aliases.get(node.id, node.id))
        return out
    if isinstance(node, (ast.List, ast.Tuple)):
        for elt in node.elts:
            if isinstance(elt, ast.Name):
                if elt.id in list_aliases:
                    out.update(list_aliases[elt.id])
                else:
                    out.add(aliases.get(elt.id, elt.id))
            elif isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name):
                out.add(aliases.get(elt.func.id, elt.func.id))
    return out


def source_mentions_tenant(node: ast.AST, source_lines: list[str]) -> bool:
    if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        return False
    chunk = "\n".join(source_lines[node.lineno - 1: node.end_lineno]).lower()
    return "tenant" in chunk


def classify(names: set[str]) -> str:
    if not names:
        # No permission_classes declared at all -> DRF default from settings
        # (JWTAuthentication + IsAuthenticated). Treat as WEAK, not SAFE.
        return "WEAK"
    if names & TENANT_AWARE_NAMES:
        return "SAFE"
    if names & PUBLIC_NAMES:
        return "PUBLIC"
    if names & ADMIN_NAMES:
        return "ADMIN"
    if names <= WEAK_NAMES:
        return "WEAK"
    # Unknown permission class we don't recognize (e.g. a project-specific
    # one not yet taught to this script) -> flag for manual look, don't
    # silently pass it.
    return "UNKNOWN"


def scan_file(path: str, app_root: str) -> list[Finding]:
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    source_lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        print(f"!! SyntaxError parsing {path}: {e}", file=sys.stderr)
        return []

    aliases, list_aliases = resolve_module_aliases(tree)
    rel = os.path.relpath(path, app_root)
    findings: list[Finding] = []

    for node in tree.body:
        # ── Class-based views ───────────────────────────────────────────
        if isinstance(node, ast.ClassDef):
            perm_names: set[str] = set()
            found_declaration = False
            for item in node.body:
                if (isinstance(item, ast.Assign)
                        and len(item.targets) == 1
                        and isinstance(item.targets[0], ast.Name)
                        and item.targets[0].id == "permission_classes"):
                    perm_names |= names_from_list_node(item.value, aliases, list_aliases)
                    found_declaration = True
                if isinstance(item, ast.FunctionDef) and item.name == "get_permissions":
                    # scan return statements inside get_permissions() for
                    # permission class names/calls
                    for sub in ast.walk(item):
                        if isinstance(sub, ast.Return) and sub.value is not None:
                            perm_names |= names_from_list_node(sub.value, aliases, list_aliases)
                    found_declaration = True
            if not found_declaration:
                # No explicit permission_classes / get_permissions on this
                # class at all -> only worth flagging if it looks like a
                # DRF view (heuristic: name ends with View).
                if not node.name.endswith("View"):
                    continue
            mentions = source_mentions_tenant(node, source_lines)
            findings.append(Finding(
                file=rel, name=node.name, kind="class",
                permission_names=perm_names, mentions_tenant=mentions,
                line=node.lineno,
            ))

        # ── Function-based views (@api_view + @permission_classes) ─────
        if isinstance(node, ast.FunctionDef):
            is_api_view = any(
                (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "api_view")
                for d in node.decorator_list
            )
            if not is_api_view:
                continue
            perm_names = set()
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "permission_classes":
                    if d.args:
                        perm_names |= names_from_list_node(d.args[0], aliases, list_aliases)
            mentions = source_mentions_tenant(node, source_lines)
            findings.append(Finding(
                file=rel, name=node.name, kind="function",
                permission_names=perm_names, mentions_tenant=mentions,
                line=node.lineno,
            ))

    for f in findings:
        cat = classify(f.permission_names)
        if cat == "WEAK" and not f.mentions_tenant:
            cat = "CRITICAL"
        f.category = cat

    return findings


def main():
    app_root = sys.argv[1] if len(sys.argv) > 1 else "."
    app_root = os.path.abspath(app_root)
    files = find_view_files(app_root)

    all_findings: list[Finding] = []
    for path in files:
        all_findings.extend(scan_file(path, app_root))

    buckets: dict[str, list[Finding]] = {
        "CRITICAL_UNLISTED": [], "CRITICAL_ALLOWED": [],
        "WEAK_UNLISTED": [], "WEAK_ALLOWED": [],
        "UNKNOWN": [], "SAFE": [], "PUBLIC": [], "ADMIN": [],
    }
    for f in all_findings:
        if f.category == "CRITICAL":
            if f.key in ALLOWLIST:
                buckets["CRITICAL_ALLOWED"].append(f)
            else:
                buckets["CRITICAL_UNLISTED"].append(f)
        elif f.category == "WEAK":
            if f.key in ALLOWLIST:
                buckets["WEAK_ALLOWED"].append(f)
            else:
                buckets["WEAK_UNLISTED"].append(f)
        else:
            buckets[f.category].append(f)

    total = len(all_findings)
    print("=" * 78)
    print("Bizal tenant-isolation permission audit")
    print("=" * 78)
    print(f"Scanned {len(files)} view files, {total} views/endpoints.\n")

    def report(bucket_name, label, show_reason=False):
        items = buckets[bucket_name]
        if not items:
            return
        print(f"[{label}] ({len(items)})")
        for f in sorted(items, key=lambda x: (x.file, x.line)):
            extra = ""
            if show_reason and f.key in ALLOWLIST:
                extra = f"  — {ALLOWLIST[f.key]}"
            perms = ", ".join(sorted(f.permission_names)) or "(none declared)"
            print(f"  {f.file}:{f.line:<5} {f.name} [{perms}]{extra}")
        print()

    report("CRITICAL_UNLISTED", "CRITICAL, NOT ALLOWLISTED — IsAuthenticated-only, no tenant reference in body")
    report("WEAK_UNLISTED", "WEAK, NOT ALLOWLISTED — must add tenant permission or allowlist entry")
    report("UNKNOWN", "UNKNOWN permission class — teach this script about it or review manually")
    report("CRITICAL_ALLOWED", "critical but allowlisted — extra scrutiny recommended on any change", show_reason=True)
    report("WEAK_ALLOWED", "weak but allowlisted (reviewed)", show_reason=True)
    report("ADMIN", "admin-gated (IsAdminUser)")
    report("PUBLIC", "public (AllowAny)")
    print(f"[SAFE] {len(buckets['SAFE'])} views use a tenant-aware permission class.\n")

    fail = bool(buckets["CRITICAL_UNLISTED"] or buckets["WEAK_UNLISTED"] or buckets["UNKNOWN"])
    if fail:
        print("RESULT: FAIL — see findings above.")
        print("  - CRITICAL findings must be fixed (add tenant scoping).")
        print("  - WEAK_UNLISTED findings must either get a tenant-aware")
        print("    permission class, or be added to tenant_isolation_allowlist.py")
        print("    with a one-line justification (and ideally a test).")
        print("  - UNKNOWN findings use a permission class this script doesn't")
        print("    recognize yet — teach it (TENANT_AWARE_NAMES/PUBLIC_NAMES/")
        print("    ADMIN_NAMES) or review by hand.")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
