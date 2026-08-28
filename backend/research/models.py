from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


def _sus_field(question_no):
    """One SUS Likert item, 1 (Aspak dakord) – 5 (Plotësisht dakord)."""
    return models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text=f'Pyetja {question_no} e SUS (1-5).',
    )


class UsabilitySurveyResponse(models.Model):
    """
    One participant's SUS (System Usability Scale) submission, filled in
    immediately after finishing the onboarding wizard — see
    research/usability_survey_sus.md for the protocol and scoring formula
    this mirrors, and research/onboarding_timing_methodology.md for how
    onboarding_duration_seconds is captured.

    tenant uses SET_NULL (not CASCADE, unlike the rest of the app's
    tenant-scoped models) plus name/business-type snapshots, because this
    is thesis research data: it must survive a test tenant later being
    deleted during cleanup, unlike ordinary tenant-owned records.
    """
    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='usability_survey_responses',
    )
    tenant_name_snapshot = models.CharField(max_length=200, blank=True)
    business_type_snapshot = models.CharField(max_length=50, blank=True)

    # Pre-question from the protocol's recruitment mix (baseline vs. new
    # user) — not part of the standard 10 SUS items, kept separate so
    # scoring stays a pure, unmodified SUS instrument.
    familiar_with_bizal = models.BooleanField(
        null=True, blank=True,
        help_text='A e njihte BizAL-in më parë pjesëmarrësi?',
    )

    q1 = _sus_field(1)
    q2 = _sus_field(2)
    q3 = _sus_field(3)
    q4 = _sus_field(4)
    q5 = _sus_field(5)
    q6 = _sus_field(6)
    q7 = _sus_field(7)
    q8 = _sus_field(8)
    q9 = _sus_field(9)
    q10 = _sus_field(10)

    # Cached at save() time from the SUS formula in usability_survey_sus.md,
    # so admin list/filter/export don't need to recompute it from q1..q10.
    sus_score = models.FloatField(null=True, blank=True, editable=False)

    # Snapshot of the auto-captured onboarding.completed activity-log
    # duration (see tenants/views.py TenantMeView.perform_update), copied in
    # at submission time rather than FK'd, again so it survives tenant/log
    # deletion.
    onboarding_duration_seconds = models.FloatField(null=True, blank=True)

    comments = models.TextField(
        blank=True,
        help_text="Komente të lira, opsionale (citate cilësore për Kapitullin 4).",
    )

    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        who = self.tenant_name_snapshot or (self.tenant.name if self.tenant_id else 'Panjohur')
        score = f'{self.sus_score:.1f}' if self.sus_score is not None else '—'
        return f'{who}: SUS {score}'

    def compute_sus_score(self):
        odd = (self.q1 - 1) + (self.q3 - 1) + (self.q5 - 1) + (self.q7 - 1) + (self.q9 - 1)
        even = (5 - self.q2) + (5 - self.q4) + (5 - self.q6) + (5 - self.q8) + (5 - self.q10)
        return round((odd + even) * 2.5, 1)

    def save(self, *args, **kwargs):
        self.sus_score = self.compute_sus_score()
        if self.tenant_id and not self.tenant_name_snapshot:
            self.tenant_name_snapshot = self.tenant.name
        if self.tenant_id and not self.business_type_snapshot:
            self.business_type_snapshot = self.tenant.business_type
        super().save(*args, **kwargs)


class SurveyConfig(models.Model):
    """
    Singleton on/off switch for the SUS popup shown after onboarding — see
    UsabilitySurveyResponse above and research/usability_survey_sus.md.

    Always exactly one row (pk=1), enforced in save()/delete() below and in
    admin.py's add/delete permissions, so there's a single toggle to flip
    once enough pilot responses have been collected, without touching code
    or redeploying.
    """
    enabled = models.BooleanField(
        default=True,
        help_text='Kur është aktiv, sondazhi SUS shfaqet pas çdo regjistrimi të ri.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Konfigurimi i sondazhit'
        verbose_name_plural = 'Konfigurimi i sondazhit'

    def __str__(self):
        return f'Sondazhi SUS: {"aktiv" if self.enabled else "joaktiv"}'

    def save(self, *args, **kwargs):
        self.pk = 1
        # Never force an INSERT here: .create()/the first get_or_create()
        # call would otherwise collide with an existing pk=1 row instead of
        # updating it. Dropping force_insert lets Django's normal
        # UPDATE-then-INSERT-if-nothing-updated logic keep this a true
        # singleton no matter how callers construct/save it.
        kwargs.pop('force_insert', None)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
