from django.db import transaction
from django.db.models import Max
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from tenants.permissions import IsTenantOwner, HasTenantFeature
from bizal.throttles import PublicReadThrottle, TenantAdminThrottle
from .models import StorefrontPage, HeroSlide, PageSection
from .serializers import StorefrontPageSerializer, HeroSlideSerializer, PageSectionSerializer


def _next_order(model, tenant):
    """
    Computes the order value for a newly created row as (current max + 1)
    for this tenant, rather than trusting whatever `order` the client sent.

    The admin frontend sends `order = <current list length>` for new items
    (append-at-the-end), which looks right until a delete has happened:
    deleting a row leaves a gap and never renumbers what's left, so
    `length` after a delete no longer equals `max(order) + 1` — it can
    collide with an existing row's order. That collision leaves the tied
    rows' relative position undefined (DB-dependent, not user-controlled),
    which is exactly the failure this function exists to prevent: it's
    the single place both ManageViews (HeroSlide/Page) route
    new-row `order` assignment through, so client input for `order` on
    create is informational at best and never actually trusted.

    select_for_update() takes a row lock on the tenant's existing rows of
    this model. Callers MUST invoke this from inside their own
    transaction.atomic() block that also performs the save — the lock is
    only held for the life of that transaction, so if the save happened
    outside it, two concurrent creates could both compute the same "next"
    value before either commits, recreating the exact collision this
    guards against.
    """
    current_max = (
        model.objects.select_for_update()
        .filter(tenant=tenant)
        .aggregate(Max('order'))['order__max']
    )
    return 0 if current_max is None else current_max + 1


class StorefrontPageListView(generics.ListAPIView):
    throttle_classes = [PublicReadThrottle]
    serializer_class = StorefrontPageSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return StorefrontPage.objects.filter(tenant=self.request.tenant, is_published=True)


class StorefrontPageDetailView(generics.RetrieveAPIView):
    throttle_classes = [PublicReadThrottle]
    serializer_class = StorefrontPageSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        return StorefrontPage.objects.filter(tenant=self.request.tenant, is_published=True)


class StorefrontPageManageView(generics.ListCreateAPIView):
    throttle_classes = [TenantAdminThrottle]
    serializer_class = StorefrontPageSerializer
    permission_classes = [IsTenantOwner, HasTenantFeature('custom_branding')]

    def get_queryset(self):
        return StorefrontPage.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        with transaction.atomic():
            order = _next_order(StorefrontPage, self.request.tenant)
            serializer.save(tenant=self.request.tenant, order=order)


class StorefrontPageUpdateView(generics.RetrieveUpdateDestroyAPIView):
    throttle_classes = [TenantAdminThrottle]
    serializer_class = StorefrontPageSerializer
    # Must match StorefrontPageManageView's feature gate — without this,
    # a tenant that loses custom_branding (e.g. downgrades) can still
    # PATCH or DELETE existing pages even though they can't create new ones.
    permission_classes = [IsTenantOwner, HasTenantFeature('custom_branding')]

    def get_queryset(self):
        return StorefrontPage.objects.filter(tenant=self.request.tenant)


class HeroSlideListView(generics.ListAPIView):
    throttle_classes = [PublicReadThrottle]
    serializer_class = HeroSlideSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return HeroSlide.objects.filter(tenant=self.request.tenant, is_active=True)


class HeroSlideManageView(generics.ListCreateAPIView):
    throttle_classes = [TenantAdminThrottle]
    serializer_class = HeroSlideSerializer
    permission_classes = [IsTenantOwner, HasTenantFeature('custom_branding')]

    def get_queryset(self):
        return HeroSlide.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        with transaction.atomic():
            order = _next_order(HeroSlide, self.request.tenant)
            serializer.save(tenant=self.request.tenant, order=order)


class HeroSlideUpdateView(generics.RetrieveUpdateDestroyAPIView):
    throttle_classes = [TenantAdminThrottle]
    serializer_class = HeroSlideSerializer
    # Same reasoning as StorefrontPageUpdateView above — must match the
    # feature gate on HeroSlideManageView so create and update/delete
    # are consistently gated on custom_branding.
    permission_classes = [IsTenantOwner, HasTenantFeature('custom_branding')]

    def get_queryset(self):
        return HeroSlide.objects.filter(tenant=self.request.tenant)


# The 8 built-in portal tabs a tenant can have (see BUILTIN_NAV_TABS in
# tenant_admin.html). A tenant only actually shows a subset of these
# depending on its type (a Hertz-style rental tenant shows 'rentals' and
# hides 'services'; a restaurant is the reverse) -- but that filtering
# already happens elsewhere (nav visibility), so PageSection doesn't need
# to duplicate it: sections for an unused page key simply never get
# requested by that tenant's admin UI.
BUILTIN_PAGE_KEYS = {'overview', 'services', 'menu', 'orders', 'rentals', 'reviews', 'blog', 'contact'}

# For each built-in page, the locked rows that represent content already
# rendered elsewhere (a real grid/list/form, or -- for Overview -- the
# auto-generated data cards). 'about' is deliberately absent from
# 'overview': the About content now lives on its own separate custom page
# instead of being an Overview card.
DEFAULT_LOCKED_SECTIONS = {
    'overview': [
        ('contact', 'Kontakti'),
        ('hours', 'Orari'),
        ('experience', 'Përvoja'),
        ('socials', 'Rrjetet Sociale'),
        ('map', 'Harta'),
        ('seo', 'Përshkrimi SEO'),
    ],
    'services': [('grid', 'Lista e Shërbimeve')],
    'menu': [('grid', 'Lista e Menusë')],
    'orders': [('view', 'Porositë')],
    'rentals': [('grid', 'Flota')],
    'reviews': [('list', 'Vlerësimet')],
    'blog': [('list', 'Artikujt')],
    'contact': [('form', 'Formulari i Kontaktit')],
}


def _validate_page_key(page_key):
    if not page_key:
        raise ValidationError({'page': 'page mungon.'})
    if page_key in BUILTIN_PAGE_KEYS:
        return
    if page_key.startswith('page:') and len(page_key) > 5:
        return
    raise ValidationError({'page': 'page e panjohur.'})


def ensure_default_sections(tenant, page_key):
    """
    Idempotently seeds the locked rows for `page_key` the first time it's
    requested, so the admin UI always has something to show for every page
    even before any custom blocks have been added. Uses get_or_create per
    lock_key rather than a bulk check-then-create so two concurrent
    requests for a brand-new page can't both decide nothing exists yet and
    each insert their own duplicate set of locked rows.
    """
    if page_key in BUILTIN_PAGE_KEYS:
        defaults = DEFAULT_LOCKED_SECTIONS.get(page_key, [])
    elif page_key.startswith('page:'):
        defaults = [('body', 'Përmbajtja e Faqes')]
    else:
        defaults = []
    for idx, (lock_key, title) in enumerate(defaults):
        PageSection.objects.get_or_create(
            tenant=tenant, page_key=page_key, lock_key=lock_key,
            defaults={'section_type': 'locked', 'title': title, 'order': idx},
        )


class PageSectionManageView(generics.ListCreateAPIView):
    """
    GET  /storefront/manage/sections/?page=<page_key>  -- list all sections
         for that page (locked rows are seeded on first request).
    POST /storefront/manage/sections/                  -- create a custom
         block; body must include `page`.

    The filter/body key is deliberately `page`, not `page_key` -- wait,
    it's `page` here on purpose but that collides with DRF's default
    pagination query param of the same name. Pagination is disabled below
    (pagination_class = None) for this view instead of renaming the param,
    since section lists per page are always small (a handful of rows) and
    never need paging.
    """
    throttle_classes = [TenantAdminThrottle]
    serializer_class = PageSectionSerializer
    permission_classes = [IsTenantOwner, HasTenantFeature('custom_branding')]
    pagination_class = None

    def get_queryset(self):
        page_key = self.request.query_params.get('page', '')
        _validate_page_key(page_key)
        ensure_default_sections(self.request.tenant, page_key)
        return PageSection.objects.filter(tenant=self.request.tenant, page_key=page_key)

    def perform_create(self, serializer):
        page_key = self.request.data.get('page', '')
        _validate_page_key(page_key)
        with transaction.atomic():
            current_max = (
                PageSection.objects.select_for_update()
                .filter(tenant=self.request.tenant, page_key=page_key)
                .aggregate(Max('order'))['order__max']
            )
            order = 0 if current_max is None else current_max + 1
            serializer.save(tenant=self.request.tenant, page_key=page_key, lock_key='', order=order)


class PageSectionPublicListView(generics.ListAPIView):
    """
    GET /storefront/sections/?page=<page_key>  -- public, read-only list of
    the *visible* sections for a page, in display order. This is what the
    public storefront (index.html) actually renders from.

    Deliberately does NOT call ensure_default_sections(): seeding locked
    rows is an admin-side concern (it happens the first time a tenant opens
    the page builder for that page). If a tenant has never touched the
    builder for this page_key, no PageSection rows exist at all yet, so
    this returns an empty list -- the frontend's fallback for "no builder
    data" is to leave that page's default, unmodified markup exactly as it
    was before this feature existed. Nothing regresses for tenants who
    never open the builder.

    Also deliberately does not raise on an unrecognized/missing `page`
    value (unlike the admin manage view) -- a bad or absent `page` query
    param from the public site should just yield "nothing to apply" rather
    than a 400, since a broken/old frontend build hitting this endpoint
    should never be able to break the storefront it's trying to render.
    """
    throttle_classes = [PublicReadThrottle]
    serializer_class = PageSectionSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        page_key = self.request.query_params.get('page', '')
        if not page_key:
            return PageSection.objects.none()
        return PageSection.objects.filter(
            tenant=self.request.tenant, page_key=page_key, hidden=False,
        ).order_by('order')


class PageSectionUpdateView(generics.RetrieveUpdateDestroyAPIView):
    throttle_classes = [TenantAdminThrottle]
    serializer_class = PageSectionSerializer
    permission_classes = [IsTenantOwner, HasTenantFeature('custom_branding')]

    def get_queryset(self):
        return PageSection.objects.filter(tenant=self.request.tenant)

    def perform_destroy(self, instance):
        # Locked rows stand in for real content (a grid, a form, a custom
        # page's body, an auto-generated card) -- deleting the row would
        # leave nothing to represent that content at all, so only hiding
        # is allowed. The admin UI never renders a delete button for these,
        # but the API rejects it too in case of a stale UI or a direct call.
        if instance.lock_key:
            raise ValidationError({'detail': 'Përmbajtja origjinale nuk mund të fshihet, vetëm të fshihet nga shikimi.'})
        super().perform_destroy(instance)
