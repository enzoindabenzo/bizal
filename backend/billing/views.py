from django.db import transaction, IntegrityError
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tenants.permissions import IsTenantOwner, HasTenantRole, HasTenantFeature
from .models import Invoice, LoyaltyAccount
from .serializers import InvoiceSerializer, InvoiceLineSerializer, LoyaltyAccountSerializer

try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None


class LoyaltyMeView(APIView):
    """
    GET /api/billing/loyalty/me/ — the current customer's points balance,
    estimated € value, and recent points history for this tenant.

    Returns 404 (not just an empty/zeroed body) when the tenant doesn't
    have the loyalty_program feature enabled — account.html's loadLoyalty()
    treats any non-OK response as "program not active for this business"
    and shows that message instead of a broken/empty points card.

    FIX: Returns 400 (not 404) when request.tenant is None, i.e. the request
    hit the main platform domain instead of a tenant subdomain. This gives
    the frontend a distinct signal to fix its routing rather than silently
    treating the main-domain hit as "loyalty not enabled for this business".
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = request.tenant
        if not tenant:
            return Response(
                {'detail': 'Este endpoint kërkon një nëndomaim biznesi, jo domenin kryesor të platformës.'},
                status=400,
            )
        if not tenant.has_feature('loyalty_program'):
            return Response({'detail': 'Loyalty program not active for this business.'}, status=404)

        try:
            with transaction.atomic():
                account, _ = LoyaltyAccount.objects.get_or_create(tenant=tenant, user=request.user)
        except IntegrityError:
            account = LoyaltyAccount.objects.get(tenant=tenant, user=request.user)
        return Response(LoyaltyAccountSerializer(account).data)


class InvoiceListCreateView(generics.ListCreateAPIView):
    serializer_class = InvoiceSerializer
    # HasTenantFeature('invoicing') ensures Starter-plan tenants cannot access
    # invoices — the invoicing feature is Pro+ only. HasTenantRole guards the
    # staff role; HasTenantFeature guards the plan tier. Both must pass.
    permission_classes = [HasTenantRole('accountant'), HasTenantFeature('invoicing')]

    ordering = ['-created_at']  # newest first, stable across deploys

    def get_queryset(self):
        qs = Invoice.objects.filter(tenant=self.request.tenant).prefetch_related('lines').order_by('-created_at')
        status = self.request.query_params.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs

    def perform_create(self, serializer):
        invoice = serializer.save(tenant=self.request.tenant)
        from activity.utils import log_activity
        log_activity(
            tenant=self.request.tenant,
            actor=self.request.user,
            verb='invoice.created',
            description=f'Created invoice {invoice.invoice_number} for {invoice.customer_name}',
            target_type='invoice',
            target_id=invoice.id,
        )


class InvoiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = InvoiceSerializer
    # Accountants can create invoices (list/create) so they must also be
    # able to view and edit individual ones — using IsTenantOwner here was
    # a bug: an accountant could POST a new invoice but got 403 on GET /id/.
    permission_classes = [HasTenantRole('accountant'), HasTenantFeature('invoicing')]

    def get_queryset(self):
        return Invoice.objects.filter(tenant=self.request.tenant).prefetch_related('lines').order_by('-created_at')


class InvoiceLineCreateView(generics.CreateAPIView):
    serializer_class = InvoiceLineSerializer
    # Lines belong to invoices; accountants manage invoices end-to-end.
    permission_classes = [HasTenantRole('accountant'), HasTenantFeature('invoicing')]

    def perform_create(self, serializer):
        # Verify the parent invoice belongs to this tenant before adding a
        # line to it. Without this, an accountant from Tenant A who knows a
        # Tenant B invoice UUID could POST to
        # /api/billing/invoices/<B_UUID>/lines/ and corrupt B's invoice.
        invoice_pk = self.kwargs['invoice_pk']
        try:
            Invoice.objects.get(pk=invoice_pk, tenant=self.request.tenant)
        except Invoice.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound('Invoice not found.')
        serializer.save(
            tenant=self.request.tenant,
            invoice_id=invoice_pk,
        )


@api_view(['GET'])
# HIGH-2 FIX: invoice_pdf was only guarded by IsTenantOwner. InvoiceListCreateView
# and InvoiceDetailView both require HasTenantFeature('invoicing'), but the PDF
# endpoint had no feature-flag gate — a tenant owner on Starter plan could call
# this endpoint directly if they obtained an invoice UUID via another channel.
@permission_classes([IsTenantOwner, HasTenantFeature('invoicing')])
def invoice_pdf(request, pk):
    """
    Generate and return a PDF invoice.
    Requires: xhtml2pdf (already in requirements.txt)
    Feature-gated to plan with pdf_export.
    """
    from .models import Invoice
    from io import BytesIO
    import html as html_lib

    if not request.tenant.has_feature('pdf_export'):
        return Response({'detail': 'PDF export not available on your plan.'}, status=403)

    try:
        invoice = Invoice.objects.prefetch_related('lines').get(
            pk=pk, tenant=request.tenant
        )
    except Invoice.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    tenant = request.tenant

    def esc(value):
        """Escape any value before it's interpolated into the raw HTML
        string below — this is an f-string template, not a Django/Jinja
        template, so nothing here is auto-escaped. Without this, a
        customer_name, note, or line description containing HTML/script
        tags would be injected straight into the generated invoice."""
        return html_lib.escape(str(value)) if value is not None else ''

    import re as _re

    def safe_hex(value, fallback):
        """
        primary_color/accent_color are now validated at the model level
        (validate_hex_color), but that only runs on full_clean()/serializer
        validation — it doesn't retroactively guarantee every row already in
        the DB is well-formed, and this value is interpolated directly into
        a raw CSS <style> block below (an f-string, not an auto-escaping
        template). html.escape() does not escape ';' or '{'/'}' , so a stored
        value like '#f;}</s>' could break out of the CSS rule. Re-validate
        strictly here and fall back to the known-safe default instead of
        trusting html.escape() alone for this particular interpolation site.
        """
        value = value or ''
        if _re.fullmatch(r'#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?', value):
            return value
        return fallback

    primary_color = safe_hex(tenant.primary_color, '#2563EB')

    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
  body {{ font-family: Arial, sans-serif; font-size: 13px; color: #111; }}
  h1   {{ color: {primary_color}; font-size: 22px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
  th   {{ background: {primary_color}; color: #fff; padding: 8px; text-align: left; }}
  td   {{ padding: 7px 8px; border-bottom: 1px solid #eee; }}
  .total {{ font-weight: bold; font-size: 15px; }}
  .meta  {{ color: #666; font-size: 12px; }}
</style></head>
<body>
  <h1>{esc(tenant.name)}</h1>
  <p class="meta">{esc(tenant.address or '')}{', ' + esc(tenant.city) if tenant.city else ''}</p>
  <p class="meta">{esc(tenant.email or '')} | {esc(tenant.phone or '')}</p>
  <hr/>
  <h2>Faturë #{esc(invoice.invoice_number or str(invoice.pk)[:8])}</h2>
  <p><strong>Klienti:</strong> {esc(invoice.customer_name or '')} &lt;{esc(invoice.customer_email or '')}&gt;</p>
  <p><strong>Data e lëshimit:</strong> {esc(invoice.issued_date or '—')}</p>
  <p><strong>Data e skadimit:</strong> {esc(invoice.due_date or '—')}</p>
  <p><strong>Statusi:</strong> {esc(invoice.get_status_display())}</p>
  <table>
    <thead><tr><th>Përshkrimi</th><th>Sasia</th><th>Çmimi/njësi</th><th>Totali</th></tr></thead>
    <tbody>
      {''.join(f"<tr><td>{esc(line.description)}</td><td>{esc(line.quantity)}</td><td>{esc(line.unit_price)} ALL</td><td>{esc(line.amount)} ALL</td></tr>" for line in invoice.lines.all())}
    </tbody>
  </table>
  <p class="total" style="text-align:right;margin-top:12px">
    TOTAL: {esc(invoice.total)} ALL
  </p>
  {f'<p>{esc(invoice.notes)}</p>' if invoice.notes else ''}
</body>
</html>"""

    try:
        if pisa is None:
            raise ImportError
        result = BytesIO()
        pdf_status = pisa.CreatePDF(html, dest=result)  # MED-4 FIX: check for render errors
        if pdf_status.err:
            return Response({'detail': 'PDF generation failed.'}, status=500)
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        import re as _re_cd
        _safe_num = _re_cd.sub(r'[^\w\-.]', '_', invoice.invoice_number or str(invoice.pk)[:8])
        # LOW-5 FIX: Sanitise invoice_number before embedding in Content-Disposition.
        # Raw invoice_number could contain double-quotes, backslashes, or newlines,
        # all of which can break or inject into the HTTP header.
        response['Content-Disposition'] = f'attachment; filename="invoice-{_safe_num}.pdf"'
        return response
    except ImportError:
        return HttpResponse(html, content_type='text/html; charset=utf-8')
