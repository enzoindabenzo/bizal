import datetime
from django.db import transaction
from django.utils import timezone as _tz
from rest_framework import serializers
from .models import ServiceProvider, Service, Appointment
from tenants.hours import hours_for_weekday, is_open_at


class ServiceProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceProvider
        fields = ('id', 'name', 'title', 'bio', 'avatar', 'specialties', 'is_active', 'staff_member')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scope staff_member choices to the current tenant so an owner
        # can't (accidentally or otherwise) link a provider to another
        # tenant's staff record via a guessed UUID.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and request.tenant:
            from staff.models import StaffMember
            self.fields['staff_member'].queryset = StaffMember.objects.filter(
                tenant=request.tenant
            )


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ('id', 'name', 'description', 'duration_minutes', 'price', 'is_active')


class AppointmentSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    provider_name = serializers.CharField(source='provider.name', read_only=True)

    class Meta:
        model = Appointment
        fields = (
            'id', 'service', 'service_name', 'provider', 'provider_name',
            'status', 'date', 'start_time', 'end_time',
            'guest_name', 'guest_email', 'guest_phone', 'notes', 'created_at',
        )
        read_only_fields = ('id', 'status', 'end_time', 'created_at')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # IDOR fix: scope service and provider FK querysets to the current
        # tenant so a visitor on Tenant A's subdomain cannot supply a
        # Tenant B service/provider UUID and have it accepted. Without this
        # scoping, AppointmentCreateView (AllowAny) would happily link the new
        # appointment to a foreign-tenant object and echo back its name/price,
        # leaking other tenants' catalogues to unauthenticated requesters.
        request = self.context.get('request')
        if request and hasattr(request, 'tenant') and request.tenant:
            self.fields['service'].queryset = Service.objects.filter(
                tenant=request.tenant, is_active=True
            )
            self.fields['provider'].queryset = ServiceProvider.objects.filter(
                tenant=request.tenant, is_active=True
            )

    def validate(self, data):
        service = data.get('service') or (self.instance.service if self.instance else None)
        start_time = data.get('start_time') or (self.instance.start_time if self.instance else None)
        if service and start_time:
            # L-3 FIX: datetime.date.today() uses the OS-level timezone.
            # timezone.localdate() respects settings.TIME_ZONE regardless of
            # the container OS timezone — defence-in-depth across all deployments.
            start_dt = datetime.datetime.combine(_tz.localdate(), start_time)
            end_dt = start_dt + datetime.timedelta(minutes=service.duration_minutes)

            # v49 FIX: guard midnight rollover. If the appointment duration pushes
            # end_dt past midnight, end_dt.date() != start_dt.date(). Storing only
            # end_dt.time() would produce an end_time that is numerically less than
            # start_time, which corrupts the stored data and silently disables the
            # double-booking overlap check (start_time__lt=end_time can never match
            # when end_time < start_time). Reject these slots with a clear message
            # rather than silently storing an inverted time pair.
            if end_dt.date() != start_dt.date():
                raise serializers.ValidationError(
                    {'start_time': (
                        'This appointment extends past midnight. '
                        'Please choose an earlier start time or a shorter service.'
                    )}
                )

            data['end_time'] = end_dt.time()

        # FIX: appointments had no server-side check against the tenant's
        # posted business_hours at all — the date/time picker on the public
        # site never even consulted business_hours for this legacy flow, so
        # an appointment could be booked at any hour of any day. Monday
        # through Saturday and Sunday can have different posted hours (or
        # Sunday can be entirely absent, i.e. closed), so hours are resolved
        # for the specific weekday of the appointment's `date`, not merged
        # across all days.
        appt_date = data.get('date') or (self.instance.date if self.instance else None)
        if start_time and appt_date:
            tenant = getattr(self.context.get('request'), 'tenant', None)
            business_hours = getattr(tenant, 'business_hours', None) if tenant else None
            if business_hours and isinstance(business_hours, dict):
                hours = hours_for_weekday(business_hours, appt_date.weekday())
                if hours is None:
                    raise serializers.ValidationError(
                        {'start_time': 'Biznesi është i mbyllur në këtë ditë.'}
                    )
                t_min = start_time.hour * 60 + start_time.minute
                if not is_open_at(business_hours, appt_date.weekday(), t_min):
                    raise serializers.ValidationError(
                        {'start_time': 'Ora e zgjedhur është jashtë orarit të punës së biznesit për këtë ditë.'}
                    )

        # Schedule enforcement: if this provider is linked to a staff.StaffMember
        # record, the appointment must fall within that staff member's posted
        # working hours for the given weekday (staff.StaffSchedule). Providers
        # with no staff_member link (contractors/freelancers with no staff
        # account) have no schedule to check against and are unrestricted here,
        # same as before this field existed.
        sched_provider = data.get('provider') or (self.instance.provider if self.instance else None)
        sched_date = data.get('date') or (self.instance.date if self.instance else None)
        sched_start = start_time
        sched_end = data.get('end_time')
        if sched_provider and sched_provider.staff_member_id and sched_date and sched_start and sched_end:
            staff_member = sched_provider.staff_member
            if not staff_member.is_active:
                raise serializers.ValidationError(
                    {'provider': 'This provider is currently unavailable.'}
                )
            from staff.models import StaffSchedule
            DAY_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            day_name = DAY_NAMES[sched_date.weekday()]
            schedule = StaffSchedule.objects.filter(staff=staff_member, day=day_name).first()
            if schedule is None:
                raise serializers.ValidationError(
                    {'start_time': 'This provider is not scheduled to work on this day.'}
                )
            if not (schedule.start_time <= sched_start and sched_end <= schedule.end_time):
                raise serializers.ValidationError(
                    {'start_time': (
                        f'This provider only works {schedule.start_time.strftime("%H:%M")}'
                        f'-{schedule.end_time.strftime("%H:%M")} on this day.'
                    )}
                )

        # Prevent double-booking: check if the provider already has a confirmed
        # or pending appointment that overlaps with the requested slot.
        provider = data.get('provider') or (self.instance.provider if self.instance else None)
        date = data.get('date') or (self.instance.date if self.instance else None)
        end_time = data.get('end_time')
        if provider and date and start_time and end_time:
            # select_for_update() on the provider row closes the TOCTOU race:
            # two concurrent appointment requests for the same slot both reach
            # this check, but the lock means only one proceeds at a time, so
            # the second will see the first's committed row and be rejected.
            with transaction.atomic():
                ServiceProvider.objects.select_for_update().get(pk=provider.pk)
                qs = Appointment.objects.filter(
                    tenant=self.context['request'].tenant,
                    provider=provider,
                    date=date,
                    status__in=('pending', 'confirmed'),
                    start_time__lt=end_time,
                    end_time__gt=start_time,
                )
                if self.instance:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    raise serializers.ValidationError(
                        {'non_field_errors': 'This provider already has an appointment during that time slot.'}
                    )

        return data
