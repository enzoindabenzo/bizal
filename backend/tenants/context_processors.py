def tenant_context(request):
    return {'tenant': getattr(request, 'tenant', None)}
