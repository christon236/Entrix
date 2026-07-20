from django.contrib import admin
from .models import AdmsDevice

# Register your models here.
@admin.register(AdmsDevice)
class AdmsDeviceAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "name", "ip_address", "is_approved", "first_seen", "last_seen")
    list_editable = ("is_approved",)
    search_fields = ("serial_number", "name")