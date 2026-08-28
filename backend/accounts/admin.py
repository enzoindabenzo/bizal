from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import User


# MEDIUM FIX: Django's stock UserCreationForm and UserChangeForm are hardcoded
# against auth.User and declare 'username' as an explicit class-level field.
# accounts.User has no 'username' column (USERNAME_FIELD = 'email'). When
# modelform_factory() rebinds the form to accounts.User, explicitly-declared
# fields are NOT removed — only auto-generated ones are. The stock forms
# therefore break the Django admin add/change views with a field-resolution
# error at runtime (visiting /django-admin/accounts/user/add/ or /change/).
#
# Fix: define custom form subclasses that bind to accounts.User and declare
# only the fields that exist on that model, then wire them into UserAdmin via
# form= and add_form=.  This is the approach documented in Django's own
# "Customising authentication in Django" guide.


class CustomUserCreationForm(UserCreationForm):
    """
    UserCreationForm bound to accounts.User.
    Excludes 'username' (not a field on this model) and uses 'email' as the
    primary identifier, matching User.USERNAME_FIELD = 'email'.
    """
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('email', 'full_name', 'role', 'tenant')


class CustomUserChangeForm(UserChangeForm):
    """
    UserChangeForm bound to accounts.User.
    Excludes 'username'; all other fields on accounts.User are available.
    """
    class Meta(UserChangeForm.Meta):
        model = User
        fields = '__all__'


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form     = CustomUserChangeForm    # MEDIUM FIX: was missing; inherited broken stock form
    add_form = CustomUserCreationForm  # MEDIUM FIX: was missing; inherited broken stock form

    list_display = ('email', 'full_name', 'role', 'tenant', 'is_active', 'created_at')
    list_filter = ('role', 'is_active', 'tenant')
    search_fields = ('email', 'full_name')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at')

    fieldsets = (
        (None, {'fields': ('id', 'email', 'password')}),
        ('Personal', {'fields': ('full_name', 'phone', 'avatar')}),
        ('Role & Tenant', {'fields': ('role', 'tenant')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'full_name', 'role', 'tenant'),
        }),
    )
