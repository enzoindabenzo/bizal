"""
dynamic_tenant_isolation_test.py  (v2 — extends the original probe)
=====================================================================
Same premise as v1: two real tenants, real rows in a real test database,
authenticate as Tenant B's owner, try to reach Tenant A's object. This
version closes three gaps found in review:

1. ROUTE DISCOVERY was limited to routes with exactly one dynamic segment
   named "pk". Nested routes (crm/leads/<lead_pk>/notes/<pk>/,
   billing/invoices/<invoice_pk>/lines/<pk>/) and non-pk leaf lookups
   (blog posts by slug, storefront pages by slug) were invisible to the
   probe — not even logged as SKIP. Now every api/ route with at least
   one dynamic segment is enumerated; each one is either tested or
   explicitly SKIPped with a stated reason.

   Assumption made explicit here (matches drf-nested-routers convention,
   confirmed against this codebase's crm/billing urls.py): the LEAF
   segment — the object actually being fetched/written — is always
   named "pk". Any earlier segment follows the "{parent}_pk" pattern and
   is resolved via the leaf object's own "{parent}_id" FK attribute
   (e.g. "lead_pk" -> obj.lead_id). A route whose leaf segment is not
   literally "pk" (slug lookups) is SKIPped with that reason stated —
   this probe does not support slug-keyed detail routes.

2. ONLY GET WAS PROBED. A WEAK/CRITICAL finding is about unauthorized
   access OR modification. This version probes GET, PATCH, and DELETE
   per route. Each method gets its OWN freshly-created object (a DELETE
   that "succeeds" as a leak must not starve the following PATCH probe
   of an object to test against). This is safe to run destructively:
   Django's TestCase wraps the whole test method in a transaction that
   is rolled back at teardown, so nothing here touches real data.

3. NO PERSISTENT STRUCTURED LOG. v1 only printed to stdout during the
   test run. This version writes one JSON line per probe — timestamp,
   request_id, route, method, model, both tenant slugs, resource pk,
   status code, verdict, elapsed_ms — to ISOLATION_REPORT_PATH (defaults
   to tenant_isolation_report.jsonl in the CWD, overwritten each run so
   CI can upload a fixed artifact path). This satisfies the "regjistrim
   formal (logje, ID kërkese, kohë ekzekutimi)" requirement directly,
   rather than only having console output from a specific run.

VERDICT CATEGORIES (per probe, i.e. per route+method):
  LEAK          Tenant B reached tenant A's object (2xx) on a
                non-public view. This is what test_no_cross_tenant_leaks
                asserts zero of.
  NO-LEAK       Tenant B was correctly rejected (403/404).
  PUBLIC_OK     View is intentionally AllowAny for this HTTP method
                (resolved dynamically via get_permissions(), same as
                v1) — a 2xx here is expected, not a finding.
  AMBIGUOUS     Any other status (most commonly 400 on PATCH — the
                object WAS found, since a tenant-scoped 404 would have
                fired before serializer validation, but no field was
                actually changed). Logged and printed, but does not by
                itself fail the assertion — flagged for manual review
                since "found but write rejected by validation" is a
                weaker signal than a clean 2xx.
  SKIP          No factory for the model, or the route shape isn't
                supported (see point 1 above) — always logged with a
                concrete reason string, never silently dropped.

Run directly:
    python manage.py test bizal.tests.dynamic_tenant_isolation_test -v 2

Report path override:
    ISOLATION_REPORT_PATH=/path/to/report.jsonl python manage.py test ...
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
import uuid

import django
from django.test import TestCase
from django.urls import get_resolver, URLPattern, URLResolver
from rest_framework import mixins
from rest_framework.test import APIClient

_TOOLING_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _TOOLING_DIR)

from tenant_isolation_factories import FACTORIES  # noqa: E402


# ── 0. Structured JSONL report writer ──────────────────────────────────

REPORT_PATH = os.environ.get("ISOLATION_REPORT_PATH", "tenant_isolation_report.jsonl")


class IsolationReportLogger:
    """Streams one JSON line per probe to disk as it happens, so a crash
    mid-run still leaves a usable partial report rather than losing
    everything that was only held in memory."""

    def __init__(self, path: str):
        self.path = path
        # truncate at the start of each run — CI wants one fixed,
        # current artifact, not an ever-growing log across runs.
        self._fh = open(self.path, "w", encoding="utf-8")

    def log(self, **fields):
        record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "request_id": uuid.uuid4().hex,
            **fields,
        }
        self._fh.write(json.dumps(record, default=str) + "\n")
        self._fh.flush()
        return record

    def close(self):
        self._fh.close()


# ── 1. Endpoint discovery: walk the URLconf for ALL api/ dynamic routes ─

_PARAM_RE = re.compile(r"<[^:>]+:([^>]+)>")


def _iter_patterns(resolver, prefix=""):
    for entry in resolver.url_patterns:
        route = str(entry.pattern)
        full = prefix + route
        if isinstance(entry, URLResolver):
            yield from _iter_patterns(entry, full)
        elif isinstance(entry, URLPattern):
            yield full, entry


def _api_routes_with_dynamic_segments():
    """Return [(full_route, URLPattern, [param_names_in_order])] for
    every api/ route with at least one dynamic segment — no longer
    filtered down to single-'pk' routes. Static-only routes (no
    dynamic segment at all) aren't isolation-relevant by definition
    (nothing to key on a specific tenant's object) and are excluded
    up front rather than reported as SKIP, to keep the SKIP list
    meaningful."""
    root = get_resolver()
    out = []
    for full, entry in _iter_patterns(root):
        if not full.startswith("api/"):
            continue
        params = _PARAM_RE.findall(full)
        if params:
            out.append((full, entry, params))
    return out


def _view_model(callback):
    view_class = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
    if view_class is None:
        return None
    qs = getattr(view_class, "queryset", None)
    if qs is not None:
        return qs.model
    serializer_class = getattr(view_class, "serializer_class", None)
    meta = getattr(serializer_class, "Meta", None)
    model = getattr(meta, "model", None)
    if model is not None:
        return model
    return None


def _model_key(model):
    return f"{model._meta.app_label}.{model.__name__}"


# A view's trailing <...:pk> segment only identifies THIS model's own row
# when the view actually looks a single object up by that pk — i.e. it uses
# one of DRF's single-object mixins (Retrieve/Update/Destroy, which all
# call GenericAPIView.get_object() keyed on self.kwargs['pk']). Checking
# for these three mixins directly (rather than e.g. "is a Retrieve*APIView")
# also correctly covers bare UpdateAPIView/DestroyAPIView views (they still
# call get_object() by pk even without Retrieve — e.g.
# reviews.PlatformReviewApproveView, a plain UpdateAPIView).
#
# ListModelMixin/CreateModelMixin are deliberately NOT sufficient on their
# own: when a ListAPIView/ListCreateAPIView's URL still has a trailing
# <...:pk> segment (e.g. hotels.SeasonalPriceView at
# room-types/<uuid:pk>/seasonal-prices/), that pk names a PARENT object used
# to filter the list, not the listed model's own pk — treating it as the
# latter silently tests the wrong thing (see the long comment on
# hotels.SeasonalPrice in tenant_isolation_factories.py for the
# false-positive LEAK this produces if not guarded against).
_SINGLE_OBJECT_MIXINS = (
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
)


def _view_is_detail_view(callback) -> bool:
    view_class = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
    if view_class is None:
        return False
    return issubclass(view_class, _SINGLE_OBJECT_MIXINS)


def _permissions_for_method(callback, method: str):
    """Resolve the REAL permission classes DRF would apply for a given
    HTTP method, by instantiating the view and calling its real
    get_permissions() — same technique as v1's _is_public_for_get, now
    parameterised so PATCH/DELETE get their own (possibly different)
    permission set rather than reusing the GET one."""
    view_class = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
    if view_class is None:
        return []
    try:
        view = view_class()
        view.request = type("FakeRequest", (), {"method": method})()
        if hasattr(view, "get_permissions"):
            return view.get_permissions()
        return [cls() for cls in getattr(view_class, "permission_classes", [])]
    except Exception:
        # Can't safely introspect -> treat as NOT public (safer default,
        # see rationale in v1: a false LEAK gets manually reviewed, a
        # false PUBLIC_OK would hide a real one).
        return [type("NonPublic", (), {})()]


def _is_public_for_method(callback, method: str) -> bool:
    perms = _permissions_for_method(callback, method)
    return any(p.__class__.__name__ == "AllowAny" for p in perms)


def _resolve_url(full_route: str, params_in_order: list[str], leaf_obj) -> str | None:
    """Substitute every <converter:name> placeholder in order. The last
    placeholder is always 'pk' (enforced by the caller before this is
    invoked) and maps to leaf_obj.pk. Any earlier placeholder named
    '{parent}_pk' is resolved via leaf_obj.{parent}_id. Returns None if
    an earlier placeholder can't be resolved this way — caller SKIPs."""
    values = []
    for i, name in enumerate(params_in_order):
        if i == len(params_in_order) - 1:
            values.append(str(leaf_obj.pk))
            continue
        if not name.endswith("_pk"):
            return None  # unsupported parent-segment naming
        fk_attr = name[: -len("_pk")] + "_id"
        val = getattr(leaf_obj, fk_attr, None)
        if val is None:
            return None
        values.append(str(val))

    it = iter(values)

    def _sub(_match):
        return next(it)

    return "/" + _PARAM_RE.sub(_sub, full_route)


# ── 2. The test case ────────────────────────────────────────────────────

PROBE_METHODS = ("GET", "PATCH", "DELETE")

# Status codes that mean "the server located and acted on the object"
_SUCCESS_CODES = {200, 201, 202, 204}
_REJECTED_CODES = {403, 404}


class DynamicCrossTenantIsolationTest(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from tenants.models import Tenant
        from accounts.models import User
        cls.tenant_a = Tenant.objects.create(
            name='Isolation Probe A', slug='iso-probe-a', business_type='restaurant',
            plan='enterprise', is_active=True,
        )
        cls.tenant_b = Tenant.objects.create(
            name='Isolation Probe B', slug='iso-probe-b', business_type='restaurant',
            plan='enterprise', is_active=True,
        )
        cls.owner_b = User.objects.create_user(
            email='owner-b@iso-probe.example', password='pass1234',
            tenant=cls.tenant_b, role='owner',
        )

    def _client_as_b(self):
        client = APIClient()
        client.defaults['HTTP_HOST'] = 'iso-probe-b.bizal.al'
        client.force_authenticate(user=self.owner_b)
        return client

    def _run_probe(self, logger: IsolationReportLogger):
        routes = _api_routes_with_dynamic_segments()
        results = {"LEAK": [], "NO-LEAK": [], "SKIP": [], "PUBLIC_OK": [], "AMBIGUOUS": []}

        for full_route, entry, params in routes:
            view_name = getattr(getattr(entry.callback, "cls", None), "__name__", str(entry.callback))

            if params[-1] != "pk":
                results["SKIP"].append((full_route, view_name, f"leaf segment is '{params[-1]}', not 'pk' — slug/other-keyed detail routes aren't supported by this probe"))
                logger.log(route=full_route, method=None, view=view_name, verdict="SKIP",
                            reason=f"leaf segment '{params[-1]}' is not 'pk'")
                continue

            # A trailing `<...:pk>` segment only means "this is the leaf
            # object's own id" on a genuine detail view (Retrieve*). On a
            # List(Create)APIView whose URL still ends in <...:pk> (e.g. a
            # nested "list children of this parent" route), that pk is a
            # PARENT filter, not this model's own id — substituting the
            # factory object's pk there tests the wrong thing and can
            # misclassify an empty-list 200 as a LEAK. See the long comment
            # on hotels.SeasonalPrice in tenant_isolation_factories.py.
            if not _view_is_detail_view(entry.callback):
                results["SKIP"].append((full_route, view_name, "URL ends in <...:pk> but the view is not a Retrieve*APIView — pk names a parent filter, not this model's own id; unsupported by this probe"))
                logger.log(route=full_route, method=None, view=view_name, verdict="SKIP",
                            reason="pk segment names a parent filter on a non-detail view")
                continue

            model = _view_model(entry.callback)
            if model is None:
                results["SKIP"].append((full_route, view_name, "could not resolve underlying model from view"))
                logger.log(route=full_route, method=None, view=view_name, verdict="SKIP",
                            reason="could not resolve underlying model from view")
                continue

            key = _model_key(model)
            factory = FACTORIES.get(key)
            if factory is None:
                results["SKIP"].append((full_route, view_name, f"no factory registered for {key}"))
                logger.log(route=full_route, method=None, view=view_name, model=key, verdict="SKIP",
                            reason=f"no factory registered for {key}")
                continue

            for method in PROBE_METHODS:
                # Fresh object per method: a DELETE "leak" earlier in
                # this loop must not starve a later method's probe.
                obj = factory(self.tenant_a)
                url = _resolve_url(full_route, params, obj)
                if url is None:
                    results["SKIP"].append((full_route, view_name, f"could not resolve parent segment(s) in '{full_route}' for {method}"))
                    logger.log(route=full_route, method=method, view=view_name, model=key, verdict="SKIP",
                                reason="could not resolve parent segment(s)")
                    continue

                is_public = _is_public_for_method(entry.callback, method)

                client = self._client_as_b()
                t0 = time.perf_counter()
                if method == "GET":
                    resp = client.get(url)
                elif method == "PATCH":
                    resp = client.patch(url, data={}, format="json")
                else:  # DELETE
                    resp = client.delete(url)
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

                if is_public:
                    verdict = "PUBLIC_OK"
                    results["PUBLIC_OK"].append((full_route, method, view_name, resp.status_code))
                elif resp.status_code in _SUCCESS_CODES:
                    verdict = "LEAK"
                    results["LEAK"].append((full_route, method, view_name, key, str(obj.pk), resp.status_code))
                elif resp.status_code in _REJECTED_CODES:
                    verdict = "NO-LEAK"
                    results["NO-LEAK"].append((full_route, method, view_name, resp.status_code))
                else:
                    verdict = "AMBIGUOUS"
                    results["AMBIGUOUS"].append((full_route, method, view_name, resp.status_code))

                logger.log(
                    route=full_route, method=method, view=view_name, model=key,
                    tenant_attacker=self.tenant_b.slug, tenant_victim=self.tenant_a.slug,
                    resource_pk=str(obj.pk), status_code=resp.status_code,
                    elapsed_ms=elapsed_ms, verdict=verdict,
                )

        return results

    def test_no_cross_tenant_leaks_on_discovered_endpoints(self):
        logger = IsolationReportLogger(REPORT_PATH)
        try:
            results = self._run_probe(logger)
        finally:
            logger.close()

        print("\n" + "=" * 78)
        from django.db import connection
        print(f"Bizal DYNAMIC cross-tenant isolation probe ({connection.vendor} test DB, real requests)")
        print(f"Structured report written to: {os.path.basename(REPORT_PATH)}")
        print("=" * 78)
        for label, n in (
            ("Tested (NO-LEAK, correctly rejected):", len(results["NO-LEAK"])),
            ("Public (expected 2xx, by design):", len(results["PUBLIC_OK"])),
            ("Skipped (no coverage yet):", len(results["SKIP"])),
            ("Ambiguous (needs manual review):", len(results["AMBIGUOUS"])),
            ("LEAKS:", len(results["LEAK"])),
        ):
            print(f"{label:<40}{n}")
        print()

        if results["SKIP"]:
            print("[SKIP — reason]")
            for row in sorted(results["SKIP"]):
                print(f"  {row[0]:<55} {row[1]:<28} -- {row[2]}")
            print()

        if results["AMBIGUOUS"]:
            print("[AMBIGUOUS — status code outside {2xx, 403, 404}; review manually]")
            for route, method, name, status in sorted(results["AMBIGUOUS"]):
                print(f"  {method:<6} {route:<50} {name:<28} -> {status}")
            print()

        if results["LEAK"]:
            print("[LEAK — tenant B reached tenant A's row]")
            for route, method, name, key, pk, status in results["LEAK"]:
                print(f"  {method:<6} {route:<50} {name:<28} model={key} pk={pk} -> {status}")
            print()

        self.assertEqual(
            results["LEAK"], [],
            f"{len(results['LEAK'])} route+method probe(s) leaked another tenant's data "
            f"— see printed report above and {os.path.abspath(REPORT_PATH)}.",
        )

    def test_dynamic_isolation_no_unexplained_gaps(self):
        """Guard against the probe silently finding nothing to test."""
        routes = _api_routes_with_dynamic_segments()
        self.assertGreater(
            len(routes), 0,
            "URLconf discovery found zero dynamic-segment api/ routes — "
            "check _api_routes_with_dynamic_segments(), the URLconf may have changed shape.",
        )