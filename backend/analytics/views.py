import csv
import io
import logging

from django.db.models import Count, Sum, Avg
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
from tenants.permissions import IsTenantOwner, HasTenantFeature
from bookings.models import Booking
from reviews.models import Review
from contact.models import ContactMessage
from bizal.ratelimit_utils import ratelimit_decorator


@api_view(['GET'])
@permission_classes([IsTenantOwner])
def analytics_dashboard(request):
    tenant = request.tenant
    if not tenant:
        return Response({'detail': 'No tenant.'}, status=400)
    if not tenant.has_feature('analytics'):
        return Response({'detail': 'Analytics not available on your plan.'}, status=403)

    start_date = request.query_params.get('start_date')
    end_date   = request.query_params.get('end_date')

    # LOW-9 FIX: Validate date format before hitting the ORM to return 400 not 500.
    from datetime import datetime as _dt
    for param_name, param_value in [('start_date', start_date), ('end_date', end_date)]:
        if param_value:
            try:
                _dt.strptime(param_value, '%Y-%m-%d')
            except ValueError:
                return Response(
                    {'detail': f'Invalid {param_name} format. Use YYYY-MM-DD.'},
                    status=400,
                )

    # ── Bookings ──────────────────────────────────────────────
    qs = Booking.objects.filter(tenant=tenant)
    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)

    total_bookings     = qs.count()
    revenue            = qs.filter(status='completed').aggregate(total=Sum('total_price'))['total'] or 0
    avg_value          = qs.filter(status='completed').aggregate(avg=Avg('total_price'))['avg'] or 0
    cancelled          = qs.filter(status='cancelled').count()
    cancellation_rate  = round((cancelled / total_bookings * 100) if total_bookings else 0, 1)

    monthly = (
        qs.filter(status='completed')
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(count=Count('id'), revenue=Sum('total_price'))
        .order_by('month')
    )

    # ── Reviews ───────────────────────────────────────────────
    review_qs = Review.objects.filter(tenant=tenant)
    if start_date:
        review_qs = review_qs.filter(created_at__date__gte=start_date)
    if end_date:
        review_qs = review_qs.filter(created_at__date__lte=end_date)
    review_stats = review_qs.aggregate(
        total=Count('id'),
        avg_rating=Avg('rating'),
    )

    # ── Contact messages ──────────────────────────────────────
    contact_qs = ContactMessage.objects.filter(tenant=tenant)
    if start_date:
        contact_qs = contact_qs.filter(created_at__date__gte=start_date)
    if end_date:
        contact_qs = contact_qs.filter(created_at__date__lte=end_date)
    total_contacts = contact_qs.count()

    # ── CRM leads ─────────────────────────────────────────────
    from crm.models import Lead
    lead_qs = Lead.objects.filter(tenant=tenant)
    if start_date:
        lead_qs = lead_qs.filter(created_at__date__gte=start_date)
    if end_date:
        lead_qs = lead_qs.filter(created_at__date__lte=end_date)
    lead_stats = lead_qs.values('status').annotate(count=Count('id'))
    leads_by_status = {row['status']: row['count'] for row in lead_stats}

    # ── New customers ─────────────────────────────────────────
    from accounts.models import User
    cust_qs = User.objects.filter(tenant=tenant, role='customer')
    if start_date:
        cust_qs = cust_qs.filter(created_at__date__gte=start_date)
    if end_date:
        cust_qs = cust_qs.filter(created_at__date__lte=end_date)
    new_customers = cust_qs.count()

    # ── Appointments ──────────────────────────────────────────
    from appointments.models import Appointment
    appt_qs = Appointment.objects.filter(tenant=tenant)
    if start_date:
        appt_qs = appt_qs.filter(created_at__date__gte=start_date)
    if end_date:
        appt_qs = appt_qs.filter(created_at__date__lte=end_date)
    appt_stats = appt_qs.values('status').annotate(count=Count('id'))
    appointments_by_status = {row['status']: row['count'] for row in appt_stats}

    # ── Orders revenue (for storefront/menu-type businesses) ────
    try:
        from orders.models import Order
        order_qs = Order.objects.filter(tenant=tenant, status__in=['delivered', 'completed'])
        if start_date:
            order_qs = order_qs.filter(created_at__date__gte=start_date)
        if end_date:
            order_qs = order_qs.filter(created_at__date__lte=end_date)
        orders_revenue = order_qs.aggregate(total=Sum('total_price'))['total'] or 0
        orders_count   = order_qs.count()
    except Exception:
        logger.exception('analytics_dashboard: failed to load orders data')
        orders_revenue = 0
        orders_count   = 0

    data = {
        'bookings': {
            'total': total_bookings,
            'revenue': float(revenue),
            'avg_value': round(float(avg_value), 2),
            'cancellation_rate': cancellation_rate,
            'monthly': [
                {
                    'month': m['month'].strftime('%Y-%m'),
                    'count': m['count'],
                    'revenue': float(m['revenue'] or 0),
                }
                for m in monthly
            ],
        },
        'reviews': {
            'total': review_stats['total'] or 0,
            'avg_rating': round(float(review_stats['avg_rating'] or 0), 2),
        },
        'contacts': {'total': total_contacts},
        'leads': leads_by_status,
        'appointments': appointments_by_status,
        'new_customers': new_customers,
        'orders': {
            'count': orders_count,
            'revenue': float(orders_revenue),
        },
        'total_revenue': float(revenue) + float(orders_revenue),
    }

    # ── CSV export (Enterprise only) ──────────────────────────
    if request.query_params.get('export') == 'csv':
        # Explicitly 403 when the feature isn't enabled rather than silently
        # returning the JSON response — a 200 with no CSV body is confusing
        # for callers and masks the real reason the export didn't happen.
        if not tenant.has_feature('csv_export'):
            return Response(
                {'detail': 'CSV export is not available on your current plan. Upgrade to Enterprise.'},
                status=403,
            )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Month', 'Bookings', 'Revenue (ALL)'])
        for row in data['bookings']['monthly']:
            writer.writerow([row['month'], row['count'], row['revenue']])
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="analytics.csv"'
        return response

    return Response(data)


class TrackEventView(APIView):
    """
    Record a frontend analytics event.
    Called by tenant pages for page_view, whatsapp_click, etc.
    No auth required — tenant identified from request.tenant.

    Rate-limited per IP to prevent bot spam that would inflate tenant
    analytics and degrade DB performance. Previously 60/min, which a single
    page load could exhaust on its own (page_view + scroll-depth + a couple
    of click events fire in quick succession), causing legitimate tracking
    to silently drop. Raised to 240/min — still well below anything a real
    visitor generates, but gives normal bursts headroom.
    """
    permission_classes = [AllowAny]

    @method_decorator(ratelimit_decorator('240/m', method='POST'))
    def post(self, request):
        tenant = request.tenant
        if not tenant:
            return Response({'detail': 'No tenant.'}, status=400)
        from .models import EVENT_TYPES
        from .utils import track
        event_type = request.data.get('event_type', 'page_view')
        # H-3 FIX: AnalyticsEvent.event_type has `choices=EVENT_TYPES`, but
        # Django `choices` are enforced only by forms/ModelForm-based
        # serializers — AnalyticsEvent.objects.create() (called inside
        # track()) accepts any string up to max_length. Since this endpoint
        # is AllowAny and only rate-limited at 60/min per IP, an
        # unauthenticated client could otherwise write ~86,400 arbitrary
        # rows/day into every tenant's analytics table, polluting
        # group-by-event_type aggregates and bloating the indexed
        # (tenant, event_type) column. Validate against the real choice set
        # before it ever reaches track()/objects.create().
        valid_event_types = {choice[0] for choice in EVENT_TYPES}
        if event_type not in valid_event_types:
            return Response({'detail': 'Invalid event_type.'}, status=400)
        page = request.data.get('page', '')
        metadata = request.data.get('metadata', {})
        track(request, tenant, event_type, page=page, metadata=metadata)
        return Response({'status': 'ok'})


# Function-based alias kept for url.py compatibility if referenced directly
# as `track_event` (DRF's as_view() makes the class callable the same way).
track_event = TrackEventView.as_view()


def _safe_csv_cell(value):
    """Prevent CSV formula injection by prefixing dangerous leading characters."""
    s = str(value) if value is not None else ''
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + s
    return s


@api_view(['GET'])
@permission_classes([IsTenantOwner, HasTenantFeature('csv_export')])
def export_bookings_csv(request):
    """GET /api/analytics/export/bookings/ — download tenant bookings as CSV.

    H-2 FIX: previously gated only by IsTenantOwner, unlike the inline CSV
    export on analytics_dashboard which explicitly checks
    tenant.has_feature('csv_export'). A Starter/Pro owner could bypass the
    plan restriction entirely by hitting this URL directly. Add the same
    feature check here (and on the other two export views below).
    """
    from bookings.models import Booking
    tenant = request.tenant
    qs = Booking.objects.filter(tenant=tenant).order_by('-created_at')

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="bookings.csv"'
    response.write('\ufeff')  # BOM for Excel UTF-8

    writer = csv.writer(response)
    writer.writerow(['ID', 'Lloji', 'Statusi', 'Emri i Klientit', 'Email', 'Telefon',
                     'Data Fillimit', 'Data Mbarimit', 'Çmimi Total', 'Data Krijimit'])
    for b in qs:
        writer.writerow([
            str(b.id), b.booking_type, b.status,
            _safe_csv_cell(b.guest_name), _safe_csv_cell(b.guest_email), _safe_csv_cell(b.guest_phone),
            b.start_date or '', b.end_date or '',
            b.total_price, b.created_at.strftime('%Y-%m-%d %H:%M'),
        ])
    return response


@api_view(['GET'])
@permission_classes([IsTenantOwner, HasTenantFeature('csv_export')])
def export_orders_csv(request):
    """GET /api/analytics/export/orders/ — download tenant orders as CSV."""
    from orders.models import Order
    tenant = request.tenant

    qs = Order.objects.filter(tenant=tenant).order_by('-created_at').prefetch_related('items__menu_item')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="orders.csv"'
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow(['ID', 'Statusi', 'Emri Klientit', 'Telefon', 'Totali', 'Artikujt', 'Data'])
    for o in qs:
        items_summary = '; '.join(f"{i.menu_item.name} x{i.quantity}" for i in o.items.all())
        writer.writerow([
            str(o.id), o.status,
            _safe_csv_cell(o.guest_name), _safe_csv_cell(o.guest_phone),
            o.total_price, _safe_csv_cell(items_summary),
            o.created_at.strftime('%Y-%m-%d %H:%M'),
        ])
    return response


@api_view(['GET'])
@permission_classes([IsTenantOwner, HasTenantFeature('csv_export'), HasTenantFeature('analytics')])
def export_customers_csv(request):
    """GET /api/analytics/export/customers/ — download tenant customers as CSV.

    H-2 / L-1 FIX: gated on both 'csv_export' (matches the other two export
    endpoints) and 'analytics' (customer-list export is part of the
    analytics feature set, so a Starter plan with analytics disabled
    shouldn't be able to dump the full customer list even if csv_export
    were ever granted independently).
    """
    from accounts.models import User
    tenant = request.tenant
    qs = User.objects.filter(tenant=tenant, role='customer').order_by('-created_at')

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="customers.csv"'
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow(['Emri', 'Email', 'Telefon', 'Qyteti', 'Data Regjistrimit'])
    for u in qs:
        writer.writerow([
            _safe_csv_cell(u.display_name), _safe_csv_cell(u.email), _safe_csv_cell(u.phone), _safe_csv_cell(u.city),
            u.created_at.strftime('%Y-%m-%d'),
        ])
    return response
