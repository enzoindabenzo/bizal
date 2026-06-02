from django.db.models import Count, Sum, Avg
from django.db.models.functions import TruncMonth
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from tenants.permissions import IsTenantOwner
from bookings.models import Booking


@api_view(['GET'])
@permission_classes([IsTenantOwner])
def analytics_dashboard(request):
    tenant = request.tenant
    if not tenant:
        return Response({'detail': 'No tenant.'}, status=400)
    if not tenant.has_feature('analytics'):
        return Response({'detail': 'Analytics not available on your plan.'}, status=403)

    qs = Booking.objects.filter(tenant=tenant)

    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)

    total_bookings = qs.count()
    revenue = qs.filter(status='completed').aggregate(total=Sum('total_price'))['total'] or 0
    avg_value = qs.filter(status='completed').aggregate(avg=Avg('total_price'))['avg'] or 0
    cancelled = qs.filter(status='cancelled').count()
    cancellation_rate = round((cancelled / total_bookings * 100) if total_bookings else 0, 1)

    monthly = (
        qs.filter(status='completed')
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(count=Count('id'), revenue=Sum('total_price'))
        .order_by('month')
    )

    data = {
        'total_bookings': total_bookings,
        'revenue': float(revenue),
        'avg_booking_value': float(avg_value),
        'cancellation_rate': cancellation_rate,
        'monthly': [
            {'month': m['month'].strftime('%Y-%m'), 'count': m['count'], 'revenue': float(m['revenue'] or 0)}
            for m in monthly
        ],
    }

    # CSV export — Enterprise only
    export = request.query_params.get('export')
    if export == 'csv' and tenant.has_feature('csv_export'):
        import csv, io
        from django.http import HttpResponse
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Month', 'Bookings', 'Revenue'])
        for row in data['monthly']:
            writer.writerow([row['month'], row['count'], row['revenue']])
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="analytics.csv"'
        return response

    return Response(data)
