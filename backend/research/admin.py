import csv

from django.contrib import admin
from django.http import HttpResponse

from .models import SurveyConfig, UsabilitySurveyResponse


@admin.register(UsabilitySurveyResponse)
class UsabilitySurveyResponseAdmin(admin.ModelAdmin):
    list_display = (
        'submitted_at', 'tenant_name_snapshot', 'business_type_snapshot',
        'familiar_with_bizal', 'onboarding_duration_seconds', 'sus_score',
    )
    list_filter = ('familiar_with_bizal', 'business_type_snapshot')
    search_fields = ('tenant_name_snapshot', 'comments')
    ordering = ('-submitted_at',)
    readonly_fields = (
        'tenant', 'tenant_name_snapshot', 'business_type_snapshot',
        'onboarding_duration_seconds', 'sus_score', 'submitted_at',
    )
    actions = ['export_as_csv']

    @admin.action(description='Eksporto rreshtat e zgjedhur si CSV (për Kapitullin 4)')
    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="bizal_sus_responses.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'submitted_at', 'tenant_name', 'business_type', 'familiar_with_bizal',
            'onboarding_duration_seconds',
            'q1', 'q2', 'q3', 'q4', 'q5', 'q6', 'q7', 'q8', 'q9', 'q10',
            'sus_score', 'comments',
        ])
        for r in queryset.order_by('submitted_at'):
            writer.writerow([
                r.submitted_at.isoformat(), r.tenant_name_snapshot, r.business_type_snapshot,
                r.familiar_with_bizal, r.onboarding_duration_seconds,
                r.q1, r.q2, r.q3, r.q4, r.q5, r.q6, r.q7, r.q8, r.q9, r.q10,
                r.sus_score, r.comments,
            ])
        return response


@admin.register(SurveyConfig)
class SurveyConfigAdmin(admin.ModelAdmin):
    """
    Singleton toggle — always exactly one row. Add/delete are disabled here
    so the list view effectively just links straight to the one instance;
    the model's own save()/delete() overrides are the hard backstop.

    list_editable puts the checkbox directly on the changelist row so
    turning data collection off (once enough pilot responses are in) or
    back on (for a fresh round) is a single tick + Save on one page —
    no clicking into the object's own change form.
    """
    list_display = ('enabled', 'updated_at')
    list_editable = ('enabled',)
    # list_editable can't include the first list_display column unless a
    # different column is the row's clickable link — updated_at takes that
    # role here (Django admin.E124).
    list_display_links = ('updated_at',)
    fields = ('enabled',)
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        return not SurveyConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        SurveyConfig.get_solo()
        return super().changelist_view(request, extra_context)
