# Tenant isolation regression check

Static (stdlib-only, no Django/DB needed) scanner + pytest gate that catches
new Django REST Framework views added to the Bizal backend without proper
tenant-isolation. Verified against the current codebase: full scan passes
clean (76 SAFE, 20 reviewed-and-allowlisted, 25 public, 3 admin-gated), and
a simulated regression (a view doing `Lead.objects.all()` behind only
`IsAuthenticated`) is correctly caught with a non-zero exit code.

## Install

Copy all three files into `bizal/backend/bizal/tests/` (or any directory
pytest already collects from). No new dependencies — pure stdlib `ast`.

## Run

```bash
# standalone, human-readable report
python3 check_tenant_isolation.py /path/to/bizal/backend

# as part of the normal test suite / CI
pytest bizal/backend/bizal/tests/test_tenant_isolation.py -v
```

Exit code 0 = pass. Non-zero = new/changed view needs a tenant-aware
permission class or a justified allowlist entry.

## What it catches

Any DRF view (class-based or `@api_view`) that:
- has no tenant-aware permission class (`IsTenantOwner`, `IsTenantStaff`,
  `HasTenantRole(...)`, `HasTenantFeature(...)`, `TenantDomainOnly`,
  `MainDomainOnly`), **and**
- relies on nothing but `IsAuthenticated` (or no `permission_classes` at
  all, which defaults to `IsAuthenticated`), **and**
- doesn't even mention `tenant` anywhere in its body (the strongest signal
  of a real gap — flagged as CRITICAL and fails the build outright).

Views that use `IsAuthenticated` + a manual `tenant=request.tenant` filter,
or that only ever touch `request.user`'s own data, are legitimate patterns
already in the codebase (`OrderDetailView`, `BookingDetailView`,
`MeOrdersView`, etc.) — those are pre-reviewed with a stated reason in
`tenant_isolation_allowlist.py` so the check passes today, but any *new*
view written the same way will be flagged until someone reviews it and adds
its own allowlist entry (or better, switches to a tenant-aware permission
class).

## Maintaining the allowlist

Add an entry only if the view is genuinely:
1. **self-scoped** — touches only `request.user`, no client-supplied ID
   that could point at another tenant's data, or
2. **manually tenant-filtered** — explicitly filters by
   `tenant=request.tenant` and checks role via
   `tenants.permissions.get_effective_role()`.

If it's neither, fix the view instead of allowlisting it.
