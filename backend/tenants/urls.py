from django.urls import path
from . import views

urlpatterns = [
    # Public
    path('info/',                                       views.TenantInfoView.as_view(),                 name='tenant-info'),
    path('signup/',                                     views.tenant_signup,                            name='tenant-signup'),
    path('create/',                                     views.create_tenant,                            name='tenant-create'),
    path('check-slug/',                                 views.check_slug,                               name='check-slug'),
    path('business-types/',                             views.business_types,                           name='business-types'),
    path('marketplace/',                                views.marketplace_list,                         name='marketplace-list'),

    # Tenant owner (requires auth)
    path('settings/',                                   views.TenantSettingsView.as_view(),             name='tenant-settings'),
    path('me/',                                         views.TenantMeView.as_view(),                   name='tenant-me'),
    path('me/change-plan/',                             views.change_plan,                              name='tenant-change-plan'),
    path('locations/',                                  views.TenantLocationListView.as_view(),         name='tenant-locations'),
    path('locations/<uuid:pk>/',                        views.TenantLocationDetailView.as_view(),       name='tenant-location-detail'),
    path('referrals/',                                  views.my_referrals,                             name='tenant-referrals'),

    # Credits / referral ledger
    path('credits/balance/',  views.credit_balance, name='credits-balance'),
    path('credits/ledger/',   views.credit_ledger,  name='credits-ledger'),
    path('credits/redeem/',   views.credit_redeem,  name='credits-redeem'),

    # Superadmin routes removed — /django-admin/ (Unfold + native ModelAdmin
    # pages, see tenants/admin.py and accounts/admin.py) is now the single
    # superadmin surface.
]