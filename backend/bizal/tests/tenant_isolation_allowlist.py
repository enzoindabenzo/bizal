"""
tenant_isolation_allowlist.py
==============================
Every entry here is a view that check_tenant_isolation.py flags as WEAK or
CRITICAL (no tenant-aware permission class), reviewed by hand and confirmed
safe for a specific, stated reason. Adding an entry here is a deliberate,
reviewable act — do it in the same PR as the view, with the reason spelled
out, so the next reviewer doesn't have to re-derive it.

Two acceptable reasons for an entry to exist:
  1. "self-scoped"    — the view only ever reads/writes request.user (or
                         objects strictly owned by request.user via a
                         `user=request.user` filter) and takes no tenant- or
                         other-user-controlled ID from the client. There is
                         no tenant to isolate because the view can only ever
                         touch the caller's own data, and a customer may
                         legitimately have data (bookings, orders, reviews,
                         appointments) across MULTIPLE tenants — narrowing
                         to a single tenant would be a bug, not a fix.
  2. "manual tenant filter" — the queryset/lookup is explicitly filtered by
                         `tenant=request.tenant` (or `request.user.tenant`)
                         inside the view body, and any role check needed is
                         done via tenants.permissions.get_effective_role().
                         This is the pattern used before HasTenantRole/
                         HasTenantFeature existed in a couple of legacy
                         views; it's correct, just not expressed as a
                         permission class, so the static scanner can't see
                         it as "SAFE" the way it sees HasTenantRole(...).

If a finding doesn't obviously fit one of those two, do NOT allowlist it —
fix the view to use a tenant-aware permission class instead.

Key format: "relative/path/to/views.py:ClassOrFunctionName"
(matches the `file:name` the checker prints in its report.)
"""

ALLOWLIST = {
    # -- Self-scoped: touch only request.user, no client-supplied ID --------
    "accounts/views.py:LogoutView":
        "self-scoped - blacklists the caller's own refresh token only.",
    "accounts/views.py:ChangePasswordView":
        "self-scoped - reads/writes request.user only; requires old_password.",
    "accounts/views.py:MeView":
        "self-scoped - get_object() always returns request.user, no pk param.",
    "accounts/views.py:MeNotificationPrefsView":
        "self-scoped - reads/writes request.user.notification_prefs only.",
    "accounts/views.py:MeDeleteView":
        "self-scoped - deactivates request.user's own account only.",
    "accounts/views.py:MeBookingsView":
        "self-scoped by design - filter(user=request.user); a customer can "
        "have bookings at multiple tenants, so this is intentionally NOT "
        "restricted to request.tenant. Optional ?tenant= param narrows "
        "further but never widens beyond request.user's own rows.",
    "accounts/views.py:MeOrdersView":
        "self-scoped, same reasoning as MeBookingsView.",
    "accounts/views.py:MeReviewsView":
        "self-scoped, same reasoning as MeBookingsView.",
    "accounts/views.py:MeAppointmentsView":
        "self-scoped, same reasoning as MeBookingsView.",
    "accounts/views.py:EmailVerificationSendView":
        "self-scoped - sends a verification email to request.user.email only.",
    "accounts/views.py:EmailVerificationConfirmView":
        "no tenant concept applies - authorization is a signed, single-use "
        "Django token (uid+token in the URL), same pattern as Django's "
        "built-in password-reset-confirm view. Explicitly rejects inactive "
        "users. permission_classes=[] is correct here, not an oversight.",
    "accounts/views.py:CustomTokenObtainPairView":
        "login endpoint - inherits permission_classes=(AllowAny,) from "
        "simplejwt's TokenObtainPairView; must be public by definition. "
        "The scanner doesn't see inherited (non-overridden) permission_classes.",
    "tenants/views.py:create_tenant":
        "self-scoped - only ever mutates request.user (guarded by "
        "`user.tenant is None`, so it can't reassign an existing owner's "
        "tenant) and creates a brand-new Tenant row; there is no existing "
        "tenant's data being read.",
    "tenants/views.py:my_referrals":
        "self-scoped - reads request.user.tenant (server-derived, not "
        "client-supplied) and that tenant's own referral records only.",

    # -- Manual tenant filter inside the view body ---------------------------
    "orders/views.py:OrderDetailView":
        "manual tenant filter - get_queryset() filters "
        "Order.objects.filter(tenant=self.request.tenant) and further "
        "restricts to the caller's own orders unless they hold a staff "
        "role on that tenant (get_effective_role()).",
    "bookings/views.py:BookingDetailView":
        "manual tenant filter - identical pattern to OrderDetailView.",
    "bookings/views.py:cancel_booking":
        "manual tenant filter - looks up the booking scoped by tenant, "
        "checks get_effective_role(request.user, request.tenant) before "
        "allowing staff-level cancellation of someone else's booking.",
    "appointments/views.py:cancel_appointment":
        "manual tenant filter - same pattern as bookings.cancel_booking.",
    "payments/views.py:create_booking_checkout":
        "manual tenant filter - looks up the booking scoped by tenant, "
        "checks `if not request.tenant: return 400`, and checks "
        "get_effective_role(request.user, request.tenant) before allowing "
        "staff-level payment initiation on someone else's booking. Same "
        "pattern as bookings.cancel_booking.",
    "payments/views.py:refund_booking_payment":
        "already tenant-aware via IsTenantOwner (checks request.tenant); "
        "additionally scopes Payment/Booking lookups by tenant=request.tenant "
        "in the body, which is what the checker is flagging.",
    "billing/views.py:LoyaltyMeView":
        "manual tenant filter - explicitly checks `if not tenant: return 400` "
        "and scopes LoyaltyAccount.objects.get_or_create(tenant=tenant, "
        "user=request.user).",
    "chatbot/views.py:staff_reply":
        "manual tenant filter - tenant is resolved from a `tenant_slug` "
        "body param (not the subdomain, since this can be called from the "
        "admin SPA), then explicitly checks "
        "`request.user.tenant == tenant` AND "
        "get_effective_role(request.user, tenant) before allowing the "
        "reply. See HIGH-1/HIGH-2 fix comments in that function.",
    "chatbot/views.py:chat":
        "manual tenant filter - tenant is resolved from a client-supplied "
        "`tenant_slug` body param, not from request.user.tenant, and "
        "deliberately does NOT require request.user to belong to that "
        "tenant: chat() is a visitor-facing widget embedded on a tenant's "
        "public storefront, meant to be usable by any authenticated "
        "platform user browsing that storefront, not just that tenant's "
        "own staff/customers. Authorization is `tenant.plan == "
        "PLAN_ENTERPRISE` + `not tenant.trial_expired` (a feature-gate, "
        "not a membership check), IsAuthenticated as an anti-abuse gate, "
        "and the SESSION_MSG_CAP / daily-cap / @ratelimit limits already "
        "in this file. It only ever reads tenant's own public business "
        "context via _load_tenant_context(tenant) (the same info shown on "
        "the storefront) and never reads another tenant's private data or "
        "data belonging to a different user.",
    "chatbot/views.py:handoff":
        "manual tenant filter - same reasoning as chatbot/views.py:chat: "
        "tenant is resolved via the client-supplied `tenant_slug`, and "
        "membership in that tenant is intentionally not required since "
        "any authenticated visitor to a tenant's public storefront can "
        "request a handoff to that tenant's staff. Access is gated by "
        "`tenant.plan == PLAN_ENTERPRISE`, `not tenant.trial_expired`, an "
        "HMAC-verified `session_id` (H-1 fix above), and a 5/min "
        "@ratelimit. The only tenant-scoped side effects are creating a "
        "CRM Lead on `tenant` and a `chatbot_handoff` notification for "
        "`tenant`'s own owners/managers - i.e. the tenant being contacted "
        "receives a lead about itself; no other tenant's data is read or "
        "written.",
    "chatbot/views.py:poll":
        "self-scoped via signed token - same pattern as "
        "EmailVerificationConfirmView. poll() never queries by tenant; "
        "it HMAC-verifies session_id into a uid via _verify_session_token() "
        "and only reads/clears the pending staff reply cache entry for that "
        "one verified uid (see MED-1 fix comment in that function), so a "
        "caller can only ever drain the reply belonging to the session "
        "token they already hold.",
}
