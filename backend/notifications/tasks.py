"""
Celery tasks for notification delivery.

Currently supports:
  - Email delivery via Django's email backend
  - SMS stub (logs only — wire up Twilio/INFOBIP_TOKEN in settings)

Usage (from other apps):
    from notifications.tasks import send_notification_email
    send_notification_email.delay(user_id, subject, html_body)
"""
from celery import shared_task
import logging
import datetime

from celery.exceptions import MaxRetriesExceededError
from django.core.mail import send_mail
from django.conf import settings
from django.db import models
from django.utils.html import strip_tags
from django.utils import timezone as _tz
logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification_email(self, user_id, subject, html_body, from_email=None):
    """
    Send a transactional email to a user.
    Retries up to 3 times on failure with 60-second backoff.
    """
    try:
        from accounts.models import User

        user = User.objects.get(pk=user_id)
        if not user.email:
            logger.warning("send_notification_email: user %s has no email", user_id)
            return

        # Plain-text fallback derived from the HTML body — some SMTP
        # relays/clients reject or mangle messages that have only an
        # html_message and no plain-text part. strip_tags() is a rough
        # approximation (no formatting/whitespace cleanup) but it's far
        # better than sending an empty plain-text part.
        plain_text = strip_tags(html_body).strip()

        send_mail(
            subject=subject,
            message=plain_text,
            html_message=html_body,
            from_email=from_email or settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        logger.info("Email sent to %s: %s", user.email, subject)
    except Exception as exc:
        logger.error("send_notification_email failed (attempt %d): %s", self.request.retries + 1, exc)
        # MEDIUM-2 FIX: catch MaxRetriesExceededError so the final permanent
        # failure is logged at the task level with the original error details,
        # not just as an unhandled exception in the Celery worker log.
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error(
                "send_notification_email permanently failed for user %s after %d retries: %s",
                user_id, self.max_retries, exc,
            )
            raise


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def send_booking_confirmation_email(self, booking_id):
    """Send booking confirmation to the guest and a notification to the owner."""
    try:
        from bookings.models import Booking

        booking = Booking.objects.select_related('tenant', 'user').get(pk=booking_id)
        tenant = booking.tenant

        guest_email = booking.guest_email
        if not guest_email and booking.user_id and booking.user.email:
            guest_email = booking.user.email
        guest_name = booking.guest_name or 'Klient'
        service = booking.resource_label or 'shërbim'
        start = booking.start_date.strftime('%d %B %Y') if booking.start_date else '—'

        if guest_email:
            subject = f"✓ Rezervimi juaj u konfirmua — {tenant.name}"
            body = f"""
<p>Përshëndetje {guest_name},</p>
<p>Rezervimi juaj te <strong>{tenant.name}</strong> u konfirmua me sukses.</p>
<ul>
  <li><strong>Shërbimi:</strong> {service}</li>
  <li><strong>Data:</strong> {start}</li>
</ul>
<p>Nëse keni pyetje, na kontaktoni: {tenant.phone or tenant.email or ''}</p>
<p>Faleminderit!</p>
"""
            send_mail(
                subject=subject,
                message=f"Rezervimi juaj u konfirmua: {service} më {start}.",
                html_message=body,
                from_email=tenant.get_reply_from_email(),
                recipient_list=[guest_email],
                fail_silently=True,
            )

        # Notify tenant owner via in-app notification.
        # M-3 FIX: this task retries up to 2 times (see @shared_task above).
        # If send_mail() above succeeds but a later step in a future edit
        # raises, or if this call itself is reached again on retry, an
        # unguarded notify_owner() would create a second in-app
        # notification for the same booking. idempotency_key makes a
        # retried call a no-op instead.
        from notifications.utils import notify_owner
        notify_owner(
            tenant,
            'booking_confirmed',
            f'Rezervim i ri: {guest_name}',
            f'{guest_name} rezervoi {service} për {start}.',
            metadata={'booking_id': str(booking_id)},
            idempotency_key=f'booking_confirmation_email:{booking_id}',
        )
    except Exception as exc:
        logger.error("send_booking_confirmation_email failed (attempt %d): %s", self.request.retries + 1, exc)
        # MEDIUM-2 FIX: log permanent failure when retries are exhausted.
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error(
                "send_booking_confirmation_email permanently failed for booking %s after %d retries: %s",
                booking_id, self.max_retries, exc,
            )
            raise


@shared_task
def send_appointment_reminders():
    """
    Send 24-hour reminders for upcoming appointments.
    Register in CELERY_BEAT_SCHEDULE to run every hour.
    """
    from appointments.models import Appointment

    # HIGH-1 FIX: datetime.date.today() returns system-local date (UTC in Docker).
    # Appointment.date values are entered in Europe/Tirane (UTC+2/+3). Between
    # 22:00-00:00 UTC the dates differ by one day — reminders fire up to 2h early.
    # timezone.localdate() honours Django's TIME_ZONE setting (Europe/Tirane).
    tomorrow = _tz.localdate() + datetime.timedelta(days=1)
    # Intentionally filter tenant__is_active=True so the query uses the
    # tenant FK index and never degenerates into a full cross-tenant scan.
    # Without a tenant filter, 500 tenants x 50 appts/day = 25 000 rows
    # are scanned on every hourly run.
    appointments = Appointment.objects.filter(
        tenant__is_active=True,
        date=tomorrow,
        status='confirmed',
        reminder_sent=False,  # never re-send; task runs hourly so without this
                               # every matching appointment gets up to 24 emails/day
        reminder_attempts__lt=3,  # LOW-5 FIX: skip after 3 failed attempts
    ).select_related('tenant', 'user', 'service')

    sent = 0
    for appt in appointments:
        # MED-2 FIX: Skip reminders for deactivated/anonymised users. A deactivated
        # user has their email set to a hashed placeholder (e.g. anon+<uuid>@deleted.bizal.al)
        # and is_active=False. Sending reminders to anonymised addresses bounces silently
        # and, worse, could expose PII if the anonymised placeholder leaks display_name.
        if appt.user_id and not appt.user.is_active:
            continue
        email = appt.user.email if appt.user_id and appt.user.email else appt.guest_email
        if not email:
            continue
        if appt.user_id and appt.user.display_name:
            name = appt.user.display_name
        else:
            name = appt.guest_name or 'Klient'
        service_name = appt.service.name if appt.service else 'takimi'
        tenant_name = appt.tenant.name

        subject = f"⏰ Kujtesë: {service_name} nesër — {tenant_name}"
        body = (
            f"Përshëndetje {name},\n\n"
            f"Ju kujdesim se keni {service_name} nesër te {tenant_name}.\n"
            f"Data: {appt.date.strftime('%d %B %Y')}"
            + (f", Ora: {appt.start_time.strftime('%H:%M')}" if appt.start_time else "") + "\n\n"
            "Nëse duhet të anuloni, na kontaktoni sa më shpejt.\n\nFaleminderit!"
        )
        try:
            # LOW-2 FIX: fail_silently=False so SMTP errors raise and are caught
            # by the except block. With fail_silently=True, send_mail() swallows
            # SMTP exceptions and returns normally — reminder_sent was then set to
            # True even though no email was delivered, permanently skipping retry.
            send_mail(
                subject=subject,
                message=body,
                from_email=appt.tenant.get_reply_from_email(),
                recipient_list=[email],
                fail_silently=False,
            )
            # MED-5 FIX (v36): Atomic conditional update — only mark as sent if
            # reminder_sent is still False at commit time. During a rolling restart,
            # two beat workers may pick up the same tick and query the same unset
            # appointments before either commits. Using filter(reminder_sent=False)
            # here means only the first UPDATE wins (returns 1); the second returns
            # 0 and we skip the sent counter to avoid double-counting.
            updated = Appointment.objects.filter(pk=appt.pk, reminder_sent=False).update(reminder_sent=True)
            if updated:
                sent += 1
            # LOW-2 NOTE: there is a small split-brain window between send_mail()
            # returning and the filter().update() above committing. If the DB
            # update fails transiently (brief network blip), reminder_sent is
            # never set and the customer will receive a duplicate reminder on the
            # next hourly run. Accepted trade-off: the window is milliseconds and
            # the conditional filter(reminder_sent=False) prevents most races.
            # A stricter fix would require a two-phase flag (reminder_sending →
            # reminder_sent) but adds DB complexity beyond the current risk level.
        except Exception as exc:
            logger.error("Reminder send failed for appt %s: %s", appt.pk, exc)
            # Increment attempts counter; task will stop retrying after 3 failures
            Appointment.objects.filter(pk=appt.pk).update(
                reminder_attempts=models.F('reminder_attempts') + 1
            )

    return f"Sent {sent} appointment reminders."


@shared_task(max_retries=0)
def send_sms_stub(phone_number, message):
    """
    SMS delivery stub — NOT IMPLEMENTED.

    M-4 FIX (v43): Previously this task logged a line and returned SUCCESS,
    making accidental callers believe SMS was delivered when nothing was sent.
    Monitoring dashboards showed green task results for every call, completely
    masking non-delivery. Now raises NotImplementedError so any accidental
    .delay() call fails visibly in the Celery worker log and the task shows
    as FAILURE rather than SUCCESS.

    To implement SMS: replace this body with Twilio or INFOBIP calls and
    remove the NotImplementedError. Example (Twilio):
        from twilio.rest import Client
        client = Client(settings.TWILIO_SID, settings.TWILIO_TOKEN)
        client.messages.create(
            to=phone_number, from_=settings.TWILIO_FROM, body=message
        )
    """
    raise NotImplementedError(
        "SMS is not configured. Implement send_sms_stub with Twilio or INFOBIP "
        "before calling it. Set TWILIO_SID/TWILIO_TOKEN/TWILIO_FROM (or equivalent) "
        "in settings and replace this NotImplementedError with the real API call."
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def notify_owner_async(self, tenant_id, notification_type, title, body, metadata=None, idempotency_key=''):
    """
    Async wrapper around notifications.utils.notify_owner.

    Previously, notify_owner() was called synchronously inside
    perform_create() on bookings and orders — this added a DB query for
    owner/manager users to every creation request before the HTTP response
    was returned. Calling this task via .delay() moves that work off the
    request thread entirely.

    M-3 FIX: this task previously had no retry handling at all (a
    transient DB error during the bulk_create simply failed the task
    silently) and notify_owner() had no idempotency guard — so the
    "retry creates duplicate notifications" risk the audit flagged wasn't
    actually reachable from this exact path before. Rather than leave
    that half-fixed, this task now (a) actually retries on transient
    failure like its sibling send_notification_email above, and (b)
    forwards idempotency_key through to notify_owner() so a retried
    attempt for the same source event is a no-op rather than a duplicate
    notification per owner/manager. Callers should pass a stable key
    derived from the source object, e.g. f'booking:{booking.id}'.

    Usage (from views):
        from notifications.tasks import notify_owner_async
        notify_owner_async.delay(
            str(request.tenant.pk), 'booking_confirmed', ...,
            idempotency_key=f'booking:{booking.id}',
        )
    """
    from tenants.models import Tenant
    try:
        tenant = Tenant.objects.get(pk=tenant_id)
    except Tenant.DoesNotExist:
        return
    from .utils import notify_owner
    try:
        notify_owner(
            tenant, notification_type, title, body,
            metadata=metadata or {}, idempotency_key=idempotency_key,
        )
    except Exception as exc:
        logger.error("notify_owner_async failed (attempt %d): %s", self.request.retries + 1, exc)
        # MEDIUM-2 FIX: log permanent failure when retries are exhausted.
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error(
                "notify_owner_async permanently failed for tenant %s after %d retries: %s",
                tenant_id, self.max_retries, exc,
            )
            raise


@shared_task
def send_booking_reminders():
    """
    Send 24-hour reminders for upcoming bookings.
    Register in CELERY_BEAT_SCHEDULE to run every hour.
    Sends to the authenticated user's email if present, falling back to
    guest_email — mirrors send_appointment_reminders. Skips bookings with
    no resolvable email (no user account and no guest_email on file).
    """
    import datetime
    from bookings.models import Booking

    # HIGH-1 FIX: same timezone fix as send_appointment_reminders above.
    tomorrow = _tz.localdate() + datetime.timedelta(days=1)
    bookings = Booking.objects.filter(
        tenant__is_active=True,
        start_date=tomorrow,
        status__in=('pending', 'confirmed'),
        reminder_sent=False,  # never re-send; task runs hourly so without this
                               # every matching booking gets up to 24 emails/day
        reminder_attempts__lt=3,  # LOW-5 FIX: skip after 3 failed attempts
    ).select_related('tenant', 'user')

    sent = 0
    for booking in bookings:
        # MED-2 FIX: Skip reminders for deactivated/anonymised users (mirrors
        # send_appointment_reminders fix above).
        if booking.user_id and not booking.user.is_active:
            continue
        email = booking.user.email if booking.user_id and booking.user.email else booking.guest_email
        if not email:
            continue
        if booking.user_id and booking.user.display_name:
            name = booking.user.display_name
        else:
            name = booking.guest_name or 'Klient'
        service = booking.resource_label or 'rezervim'
        tenant_name = booking.tenant.name
        subject = f"⏰ Kujtesë: {service} nesër — {tenant_name}"
        body = (
            f"Përshëndetje {name},\n\n"
            f"Ju kujdesim se keni {service} nesër te {tenant_name}.\n"
            f"Data: {booking.start_date.strftime('%d %B %Y')}"
            + (f", Ora: {booking.start_time.strftime('%H:%M')}" if booking.start_time else "") + "\n\n"
            "Nëse duhet të anuloni, na kontaktoni sa më shpejt.\n\nFaleminderit!"
        )
        try:
            # LOW-2 FIX: fail_silently=False so SMTP errors raise into the except
            # block. reminder_sent is only set on confirmed delivery.
            send_mail(
                subject=subject,
                message=body,
                from_email=booking.tenant.get_reply_from_email(),
                recipient_list=[email],
                fail_silently=False,
            )
            # MED-5 FIX (v36): Atomic conditional update — see matching comment
            # in send_appointment_reminders above.
            updated = Booking.objects.filter(pk=booking.pk, reminder_sent=False).update(reminder_sent=True)
            if updated:
                sent += 1
            # LOW-2 NOTE: same split-brain window as send_appointment_reminders —
            # see comment there. Accepted trade-off; duplicate risk is minimal.
        except Exception as exc:
            logger.error("Booking reminder send failed for booking %s: %s", booking.pk, exc)
            # Increment attempts counter; task will stop retrying after 3 failures
            Booking.objects.filter(pk=booking.pk).update(
                reminder_attempts=models.F('reminder_attempts') + 1
            )

    return f"Sent {sent} booking reminders."
