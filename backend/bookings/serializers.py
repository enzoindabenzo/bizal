from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from .models import Booking, BOOKING_TYPE_CHOICES
from tenants.hours import hours_for_weekday, is_open_at


class BookingSerializer(serializers.ModelSerializer):
    user_name  = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    booking_type = serializers.ChoiceField(choices=BOOKING_TYPE_CHOICES, required=False)
    resource_status = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = (
            'id', 'booking_type', 'status', 'start_date', 'end_date',
            'start_time', 'end_time', 'resource_label',
            'guest_name', 'guest_email', 'guest_phone', 'guest_count',
            'total_price', 'deposit_paid', 'notes', 'user_name', 'user_email', 'created_at',
            'resource_type', 'resource_id', 'resource_status',
        )
        # SECURITY FIX: total_price used to be a plain writable field. Any
        # client (including an anonymous, unauthenticated POST) could submit
        # an arbitrary total_price, which admin_update_booking later feeds
        # straight into award_points() when staff mark the booking
        # 'completed' — letting a customer inflate their own loyalty points
        # by lying about what they paid. total_price is now read-only here
        # and computed server-side in create()/update() from the actual
        # resource (Service.price, RentalItem.price_per_day, or
        # RoomType.base_price), mirroring how orders.OrderItem snapshots
        # price from menu_item/product and how RoomBookingListCreateView
        # already computes total_price = base_price * nights.
        read_only_fields = ('id', 'status', 'total_price', 'deposit_paid', 'user_name', 'user_email', 'created_at')

    def get_user_name(self, obj):
        return obj.user.display_name if obj.user else obj.guest_name

    def get_user_email(self, obj):
        return obj.user.email if obj.user else obj.guest_email

    def get_resource_status(self, obj):
        # Surfaces the rental item's current availability (e.g. a car) next
        # to the booking, distinct from the booking's own pending/confirmed/
        # active status — used by the tenant-side customer profile to show
        # an "Availability" field on rental bookings (cars, equipment, etc).
        if obj.booking_type != 'rental' or obj.resource_type != 'rental_item' or not obj.resource_id:
            return None
        try:
            from rentals.models import RentalItem
            item = RentalItem.objects.only('status').get(id=obj.resource_id)
            return item.status
        except RentalItem.DoesNotExist:
            return None

    def validate(self, data):
        if not data.get('booking_type'):
            tenant = self.context['request'].tenant
            TYPE_MAP = {
                'clinic':             'appointment',
                'barbershop':         'appointment',
                'spa':                'appointment',
                'gym':                'appointment',
                'tattoo':             'appointment',
                'lawyer':             'appointment',
                'auto_repair':        'appointment',
                'language_school':    'appointment',
                'tutoring':           'appointment',
                'driving_school':     'appointment',
                'restaurant':         'table_reservation',
                'bar':                'table_reservation',
                'bakery':             'table_reservation',
                'hotel':              'room_booking',
                'car_rental':         'rental',
                'property_rental':    'rental',
                'equipment_rental':   'rental',
                'boat_rental':        'rental',
            }
            bt = getattr(tenant, 'business_type', '') if tenant else ''
            data['booking_type'] = TYPE_MAP.get(bt, 'appointment')

        # FIX #4: Overlap check for hotel room bookings.
        # RentalItem already has is_available_for(); mirror that logic here
        # for room_booking types so two guests cannot book the same room on
        # overlapping dates.
        booking_type = data.get('booking_type', '')
        resource_type = data.get('resource_type', '')
        resource_id = data.get('resource_id', '')
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        # FIX: start_date/end_date were only constrained client-side (the
        # booking modal's date <input> uses min="${todayStr}"), so a direct
        # API call — or a user editing the request in devtools — could
        # still submit a booking for a date that has already passed. Applies
        # to every booking_type that carries dates (room_booking, rental,
        # table_reservation, class, event, delivery), not just rooms/rentals,
        # since none of them had this check before.
        #
        # PATCH REGRESSION FIX: on a partial_update(), `data` only contains
        # the fields actually sent in the request body. If the client PATCHes
        # e.g. {"status": "confirmed"} without start_date, data.get('start_date')
        # is None here even though the existing instance already has a valid
        # start_date. Fall back to self.instance's current value when the
        # field wasn't part of this request, so PATCHes that don't touch the
        # date fields aren't skipped/mis-validated, while POST (self.instance
        # is None) and any PATCH that does send new dates still validate fully.
        if 'start_date' in data and start_date and start_date < timezone.localdate():
            raise serializers.ValidationError(
                {'start_date': 'Data e fillimit nuk mund të jetë në të kaluarën.'}
            )

        ordering_start_date = start_date if 'start_date' in data else (
            self.instance.start_date if self.instance is not None else None
        )
        if end_date and ordering_start_date and end_date < ordering_start_date:
            raise serializers.ValidationError(
                {'end_date': 'Data e mbarimit nuk mund të jetë para datës së fillimit.'}
            )

        if (
            booking_type == 'room_booking'
            and resource_type == 'room'
            and resource_id
            and start_date
            and end_date
        ):
            try:
                from hotels.models import Room, is_room_available
                # MED-6 FIX: the inner atomic() (savepoint) is removed. The
                # outer transaction.atomic() in BookingListCreateView.create()
                # already wraps is_valid()+perform_create(), so select_for_update()
                # holds the PostgreSQL row lock at the transaction level — not just
                # the savepoint level — all the way through the INSERT. The inner
                # atomic() was redundant and made the lock scope non-obvious.
                # LOW FIX: corrected class name from 'BookingCreateView' (does not
                # exist) to 'BookingListCreateView' (actual class in bookings/views.py).
                room = Room.objects.select_for_update().get(
                    pk=resource_id, tenant=self.context['request'].tenant
                )
                instance = self.instance
                exclude_id = instance.pk if instance else None
                if not is_room_available(room, start_date, end_date, exclude_booking_id=exclude_id):
                    raise serializers.ValidationError(
                        {'non_field_errors': 'This room is not available for the selected dates.'}
                    )
            except Room.DoesNotExist:
                raise serializers.ValidationError({'resource_id': 'Room not found.'})

        # The public storefront only lists RoomType objects (guests pick "a
        # Deluxe Room", not a specific room number), so resource_type here is
        # 'room_type', not 'room'. Resolve it to one concrete, available Room
        # now (holding the row lock through save()) and rewrite resource_type/
        # resource_id to point at that Room — matching the internal 'room'
        # representation used everywhere else (is_room_available, RoomBooking
        # linkage in perform_create, resource_status lookups, etc).
        if (
            booking_type == 'room_booking'
            and resource_type == 'room_type'
            and resource_id
            and start_date
            and end_date
        ):
            from hotels.models import Room, RoomType, is_room_available
            try:
                room_type = RoomType.objects.get(pk=resource_id, tenant=self.context['request'].tenant)
            except RoomType.DoesNotExist:
                raise serializers.ValidationError({'resource_id': 'Room type not found.'})

            instance = self.instance
            exclude_id = instance.pk if instance else None
            candidate_rooms = Room.objects.select_for_update().filter(
                tenant=self.context['request'].tenant, room_type=room_type, status='available',
            ).order_by('room_number')
            chosen_room = next(
                (r for r in candidate_rooms if is_room_available(r, start_date, end_date, exclude_booking_id=exclude_id)),
                None,
            )
            if chosen_room is None:
                raise serializers.ValidationError(
                    {'non_field_errors': 'No rooms of this type are available for the selected dates.'}
                )
            data['resource_type'] = 'room'
            data['resource_id'] = str(chosen_room.pk)
            self._resolved_room = chosen_room  # consumed in _compute_total_price, not part of `data`

        # Overlap check for rental bookings — mirrors the room_booking check above.
        # Previously, is_available_for() was only called from a read-only GET endpoint,
        # meaning the actual booking creation POST had no server-side overlap validation.
        if (
            booking_type == 'rental'
            and resource_type == 'rental_item'
            and resource_id
            and start_date
            and end_date
        ):
            try:
                from rentals.models import RentalItem
                # MED-6 FIX: inner atomic() removed — see room_booking comment above.
                item = RentalItem.objects.select_for_update().get(
                    pk=resource_id, tenant=self.context['request'].tenant
                )
                instance = self.instance
                exclude_id = instance.pk if instance else None
                if not item.is_available_for(start_date, end_date, exclude_booking_id=exclude_id):
                    raise serializers.ValidationError(
                        {'non_field_errors': 'This rental item is not available for the selected dates.'}
                    )
            except RentalItem.DoesNotExist:
                raise serializers.ValidationError({'resource_id': 'Rental item not found.'})

        # MEDIUM-4 FIX: For all other booking types (table_reservation,
        # appointment, class, event, delivery) resource_id was previously
        # accepted as arbitrary free-text with no validation. Validate that
        # it is a valid UUID when provided, regardless of booking type.
        # room_booking and rental are already fully validated above.
        if resource_id and booking_type not in ('room_booking', 'rental'):
            import uuid as _uuid
            try:
                _uuid.UUID(str(resource_id))
            except (ValueError, AttributeError):
                raise serializers.ValidationError(
                    {'resource_id': 'Must be a valid UUID.'}
                )

        # FIX: start_time was only constrained client-side (the booking
        # modal's <select> only offers slots within business_hours). A direct
        # API call could still submit any start_time, including outside the
        # tenant's posted hours. Validate server-side for booking types where
        # a specific time of day is meaningful: appointments (clinics, salons,
        # etc.) and table_reservation (restaurants/bars).
        #
        # NOTE: this used to merge every range in business_hours into one
        # min(open)/max(close) window, which meant a tenant with shorter
        # Sunday hours (e.g. Mon-Sat 09:00-20:00, Sun 10:00-16:00) would
        # accept a 19:00 Sunday booking because Monday-Saturday goes that
        # late. Hours are now resolved for the actual weekday being booked
        # (falling back to today if no start_date was submitted), so Monday
        # through Saturday and Sunday are each checked against their own
        # posted hours — and a day with no entry at all is treated as closed.
        start_time = data.get('start_time')
        if booking_type in ('appointment', 'table_reservation') and start_time:
            tenant = self.context['request'].tenant
            business_hours = getattr(tenant, 'business_hours', None) if tenant else None
            if business_hours and isinstance(business_hours, dict):
                booking_date = start_date or timezone.localdate()
                hours = hours_for_weekday(business_hours, booking_date.weekday())
                if hours is None:
                    raise serializers.ValidationError(
                        {'start_time': 'Biznesi është i mbyllur në këtë ditë.'}
                    )
                t_min = start_time.hour * 60 + start_time.minute
                if not is_open_at(business_hours, booking_date.weekday(), t_min):
                    raise serializers.ValidationError(
                        {'start_time': 'Ora e zgjedhur është jashtë orarit të punës së biznesit për këtë ditë.'}
                    )

        return data

    def _compute_total_price(self, data):
        """
        SECURITY FIX: total_price used to be a plain client-writable field —
        any request (including anonymous ones) could submit an arbitrary
        amount, which admin_update_booking later fed straight into
        award_points(). This computes the real price server-side from the
        actual priced resource, the same way orders.OrderItem snapshots price
        from menu_item/product rather than trusting the client.

        Returns None (not 0) when there's no resource to derive a price from
        (e.g. plain table reservations, or a booking with no resource_id at
        all) — callers should fall back to the existing total_price (on
        update) or 0 (on create), and staff can set the real amount later via
        admin_update_booking, which now accepts an explicit total_price for
        exactly this case.
        """
        booking_type = data.get('booking_type', '')
        resource_type = data.get('resource_type', '')
        resource_id = data.get('resource_id', '')
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        if booking_type == 'rental' and resource_type == 'rental_item' and resource_id and start_date and end_date:
            from rentals.models import RentalItem
            try:
                item = RentalItem.objects.get(pk=resource_id, tenant=self.context['request'].tenant)
            except RentalItem.DoesNotExist:
                return None
            # Inclusive day count: same start/end date = 1 day. Matches
            # calcRentalDays() in the storefront JS exactly (start-day
            # inclusive), so the number of days billed is the number of days
            # shown to the customer before they submit.
            days = (end_date - start_date).days + 1
            subtotal = item.price_per_day * days
            # Longer-rental discount, mirroring calcRentalDiscountPct() in the
            # storefront JS: 1-2 days 0%, 3-6 days 5%, 7+ days 10%. Kept here
            # (not just client-side) so the price the server actually charges
            # matches the breakdown already shown to the customer in the
            # booking modal — otherwise this fix would silently overcharge
            # relative to what they were quoted.
            if days >= 7:
                discount_pct = 10
            elif days >= 3:
                discount_pct = 5
            else:
                discount_pct = 0
            return (subtotal * (100 - discount_pct) / 100).quantize(Decimal('0.01'))

        if booking_type == 'room_booking' and resource_type == 'room' and resource_id and start_date and end_date:
            # If validate() just resolved this from a room_type, reuse that
            # instance directly rather than re-querying.
            room = getattr(self, '_resolved_room', None)
            if room is None or str(room.pk) != str(resource_id):
                from hotels.models import Room
                try:
                    room = Room.objects.select_related('room_type').get(
                        pk=resource_id, tenant=self.context['request'].tenant,
                    )
                except Room.DoesNotExist:
                    return None
            nights = max((end_date - start_date).days, 1)
            return room.room_type.base_price * nights

        if booking_type == 'appointment' and resource_type == 'service' and resource_id:
            from appointments.models import Service
            try:
                service = Service.objects.get(pk=resource_id, tenant=self.context['request'].tenant)
            except Service.DoesNotExist:
                return None
            return service.price

        # table_reservation, class, event, delivery, or any booking without a
        # priced resource_id: no server-derivable price. Staff set this later
        # via admin_update_booking.
        return None

    def create(self, validated_data):
        price = self._compute_total_price(validated_data)
        validated_data['total_price'] = price if price is not None else 0
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # A PATCH (BookingDetailView.partial_update) can change dates or
        # resource_id/type — e.g. rescheduling a rental to a longer date
        # range — so total_price must be recomputed from the *merged* state,
        # not just from whatever fields happened to be in this request.
        merged = {
            'booking_type': validated_data.get('booking_type', instance.booking_type),
            'resource_type': validated_data.get('resource_type', instance.resource_type),
            'resource_id': validated_data.get('resource_id', instance.resource_id),
            'start_date': validated_data.get('start_date', instance.start_date),
            'end_date': validated_data.get('end_date', instance.end_date),
        }
        price = self._compute_total_price(merged)
        if price is not None:
            validated_data['total_price'] = price
        # else: leave total_price untouched (e.g. table reservations, or a
        # staff-set price from admin_update_booking) — nothing to recompute.
        return super().update(instance, validated_data)
