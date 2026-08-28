from django.db import models
from bizal.base_models import TenantScopedUUIDModel

LEAD_STATUS = [
    ('new', 'New'),
    ('contacted', 'Contacted'),
    ('qualified', 'Qualified'),
    ('proposal', 'Proposal Sent'),
    ('won', 'Won'),
    ('lost', 'Lost'),
]

LEAD_SOURCE = [
    ('website', 'Website'),
    ('referral', 'Referral'),
    ('social', 'Social Media'),
    ('walk_in', 'Walk-in'),
    ('chatbot', 'Chatbot'),
    ('other', 'Other'),
]


class Lead(TenantScopedUUIDModel):
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    source = models.CharField(max_length=30, choices=LEAD_SOURCE, default='website')
    status = models.CharField(max_length=20, choices=LEAD_STATUS, default='new')
    notes = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        'accounts.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='assigned_leads'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} [{self.get_status_display()}]"


class LeadNote(TenantScopedUUIDModel):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='lead_notes')
    author = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)
    body = models.TextField()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note on {self.lead.name}"
