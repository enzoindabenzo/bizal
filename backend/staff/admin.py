from django.contrib import admin
from .models import StaffMember, StaffSchedule


class StaffScheduleInline(admin.TabularInline):
    model = StaffSchedule
    extra = 0


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'position', 'is_active', 'tenant')
    list_filter = ('role', 'is_active', 'tenant')
    search_fields = ('user__email', 'position')
    inlines = [StaffScheduleInline]
