

def tenant_context(request):
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return {'tenant': None}

    return {
        'tenant': tenant,
        'tenant_plan': tenant.plan,
        'tenant_trial_expired': tenant.trial_expired,
        'tenant_trial_days_remaining': tenant.trial_days_remaining,
        'tenant_on_trial': tenant.plan == 'trial',
    }
