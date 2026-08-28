from django.db import models
from bizal.base_models import TenantScopedUUIDModel


class ActivityLog(TenantScopedUUIDModel):
    """
    A simple audit trail entry: "<actor> <verb> <description>" within a
    tenant, e.g. "John confirmed booking #1234" or
    "Admin activated this business".

    Kept intentionally generic (no per-model foreign keys) so any app can
    log an event without introducing a dependency on activity from that
    app — see activity.utils.log_activity().
    """

    # Who did it. Nullable + a name snapshot so the log entry still reads
    # sensibly if the user account is later deleted.
    actor = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='activity_logs',
    )
    actor_name = models.CharField(max_length=200, blank=True)

    # What happened. `verb` is a short machine-friendly tag (e.g.
    # "booking.confirmed"), `description` is the human-readable sentence
    # shown in the activity feed.
    verb = models.CharField(max_length=100)
    description = models.CharField(max_length=255)

    # Optional pointer to the object this entry is about, so a UI can
    # link "Booking #1234" -> /bookings/1234.
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.CharField(max_length=64, blank=True)

    # Anything extra worth keeping (old/new values, amounts, etc.)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', '-created_at']),
        ]

    def __str__(self):
        who = self.actor_name or 'System'
        return f'{who}: {self.description}'
