from django.contrib import admin
from .models import RoomType, Room, SeasonalPrice


class SeasonalPriceInline(admin.TabularInline):
    model = SeasonalPrice
    extra = 0
    fields = ('name', 'start_date', 'end_date', 'price')


class RoomInline(admin.TabularInline):
    model = Room
    extra = 0
    fields = ('room_number', 'floor', 'status', 'room_type')
    readonly_fields = ('room_number',)


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'capacity', 'base_price')
    list_filter = ('tenant',)
    search_fields = ('name', 'tenant__name')
    inlines = [SeasonalPriceInline]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('room_number', 'tenant', 'room_type', 'floor', 'status')
    list_filter = ('tenant', 'status', 'room_type')
    search_fields = ('room_number', 'tenant__name')


@admin.register(SeasonalPrice)
class SeasonalPriceAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'room_type', 'start_date', 'end_date', 'price')
    list_filter = ('tenant',)
    search_fields = ('name', 'tenant__name')
