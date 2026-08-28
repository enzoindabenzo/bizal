from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.permissions import IsOwnTenantOwnerOrManager
from .models import SurveyConfig, UsabilitySurveyResponse
from .serializers import UsabilitySurveyResponseSerializer


class SusConfigView(APIView):
    """
    GET /api/research/sus/config/ — public on/off flag the onboarding
    frontend checks before opening the SUS popup at all. AllowAny (not
    IsOwnTenantOwnerOrManager like the submit endpoint below) because this
    fires as soon as onboarding finishes, before there's any survey data to
    protect — it's just a feature flag, not participant data.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'enabled': SurveyConfig.get_solo().enabled})


class UsabilitySurveyResponseCreateView(generics.CreateAPIView):
    """
    POST /api/research/sus/ — submit the in-app SUS popup shown right after
    the onboarding wizard's finishOnboarding() call. See
    research/usability_survey_sus.md for the questionnaire this mirrors.

    Restricted to the tenant's own owner/manager (same permission the
    onboarding PATCH itself uses) so the popup can only be submitted by the
    person who actually just went through onboarding — not the general
    public, and not staff of other tenants.
    """
    serializer_class = UsabilitySurveyResponseSerializer
    permission_classes = [IsOwnTenantOwnerOrManager]

    def perform_create(self, serializer):
        tenant = self.request.user.tenant
        duration = self._onboarding_duration_seconds(tenant)
        serializer.save(
            tenant=tenant,
            tenant_name_snapshot=tenant.name,
            business_type_snapshot=tenant.business_type,
            onboarding_duration_seconds=duration,
        )

    def _onboarding_duration_seconds(self, tenant):
        # Prefer the exact duration TenantMeView.perform_update already
        # logged for this tenant's onboarding.completed event, so the two
        # numbers (activity log vs. survey record) never drift apart. Fall
        # back to a fresh computation only if that log entry is missing
        # (e.g. instrumentation added after this tenant had already
        # finished onboarding).
        from activity.models import ActivityLog

        entry = (
            ActivityLog.objects
            .filter(tenant=tenant, verb='onboarding.completed')
            .order_by('-created_at')
            .first()
        )
        if entry and 'duration_seconds' in entry.metadata:
            return entry.metadata['duration_seconds']
        return round((timezone.now() - tenant.created_at).total_seconds(), 1)
