from datetime import date, time

from django.test import TestCase

from tenants.models import Tenant
from accounts.models import User
from inventory.models import ProductCategory, Product
from menu.models import MenuCategory, MenuItem
from rentals.models import RentalItem
from staff.models import StaffMember, StaffSchedule
from subscriptions.models import CustomerSubscription
from blog.models import BlogTag, BlogPost, STATUS_PUBLISHED
from bookings.models import Booking
from contact.models import ContactMessage, PlatformInquiry
from crm.models import Lead, LeadNote
from payments.models import Payment, WebhookEvent
from reviews.models import Review
from reviews.platform_models import PlatformReview
from storefront.models import StorefrontPage, PageSection, HeroSlide


def make_tenant(slug, business_type='retail'):
    return Tenant.objects.create(
        name=slug.title(), slug=slug, plan='enterprise',
        is_active=True, business_type=business_type,
    )


def make_user(email, tenant, role='owner'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


class StrGapsTest(TestCase):
    def setUp(self):
        self.tenant = make_tenant('strgaps')
        self.user = make_user('owner@strgaps.com', self.tenant)

    def test_inventory_str(self):
        cat = ProductCategory.objects.create(tenant=self.tenant, name='Cat', slug='cat')
        self.assertEqual(str(cat), 'Cat')
        prod = Product.objects.create(tenant=self.tenant, category=cat, name='Prod', price=10, stock=5)
        self.assertEqual(str(prod), 'Prod')

    def test_menu_str(self):
        cat = MenuCategory.objects.create(tenant=self.tenant, name='Drinks')
        self.assertEqual(str(cat), 'Drinks')
        item = MenuItem.objects.create(tenant=self.tenant, category=cat, name='Cola', price=2)
        self.assertEqual(str(item), 'Cola - 2')

    def test_rentals_str_and_exclude(self):
        item = RentalItem.objects.create(
            tenant=self.tenant, name='Car1', rental_type='car',
            price_per_day=100, status='available',
        )
        self.assertEqual(str(item), 'Car1 (car)')
        booking = Booking.objects.create(
            tenant=self.tenant, user=self.user, booking_type='rental',
            status='confirmed', resource_id=str(item.pk), resource_type='rental_item',
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 5),
        )
        # exclude_booking_id branch: excluding the only overlapping booking
        # should make the item available again for those dates.
        available = item.is_available_for(date(2026, 1, 1), date(2026, 1, 5), exclude_booking_id=booking.pk)
        self.assertTrue(available)

    def test_staff_str(self):
        staff_user = make_user('staff1@strgaps.com', self.tenant, role='staff')
        member = StaffMember.objects.create(tenant=self.tenant, user=staff_user, role='manager')
        self.assertIn('manager', str(member))
        sched = StaffSchedule.objects.create(
            tenant=self.tenant, staff=member, day='monday',
            start_time=time(9, 0), end_time=time(17, 0),
        )
        self.assertIn('monday', str(sched))

    def test_subscriptions_str(self):
        sub = CustomerSubscription.objects.create(
            tenant=self.tenant, customer=self.user, name='Gym Pass', price=20,
        )
        self.assertIn('Gym Pass', str(sub))

    def test_blog_str_and_slugify(self):
        tag = BlogTag.objects.create(tenant=self.tenant, name='News')
        self.assertEqual(str(tag), 'News')
        self.assertEqual(tag.slug, 'news')
        post = BlogPost.objects.create(
            tenant=self.tenant, author=self.user, title='Hello World',
            body='body text', status=STATUS_PUBLISHED,
        )
        self.assertEqual(str(post), 'Hello World')
        self.assertEqual(post.slug, 'hello-world')
        self.assertIsNotNone(post.published_at)

    def test_bookings_str(self):
        b = Booking.objects.create(
            tenant=self.tenant, user=self.user, booking_type='appointment', status='pending',
        )
        self.assertIn('appointment', str(b))

    def test_contact_str(self):
        msg = ContactMessage.objects.create(
            tenant=self.tenant, name='John', email='j@example.com', message='hi',
        )
        self.assertIn('John', str(msg))
        inquiry = PlatformInquiry.objects.create(
            name='Jane', email='jane@example.com', message='hi there',
        )
        self.assertIn('Jane', str(inquiry))

    def test_crm_str(self):
        lead = Lead.objects.create(tenant=self.tenant, name='Lead1', status='new')
        self.assertIn('Lead1', str(lead))
        note = LeadNote.objects.create(tenant=self.tenant, lead=lead, author=self.user, body='note body')
        self.assertIn('Lead1', str(note))

    def test_payments_str(self):
        payment = Payment.objects.create(
            tenant=self.tenant, user=self.user, amount=50, currency='EUR', payment_type='order',
        )
        self.assertIn('order', str(payment))
        event = WebhookEvent.objects.create(
            stripe_event_id='evt_1', event_type='checkout.session.completed', status='processed',
        )
        self.assertIn('checkout.session.completed', str(event))

    def test_reviews_str(self):
        review = Review.objects.create(
            tenant=self.tenant, user=self.user, rating=5, comment='great', is_approved=True,
        )
        self.assertIn('5', str(review))
        platform_review = PlatformReview.objects.create(
            reviewer_name='Anna', rating=4, comment='nice', business_name='',
        )
        self.assertIn('anonymous', str(platform_review))
        platform_review2 = PlatformReview.objects.create(
            reviewer_name='Bob', rating=5, comment='great', business_name='Bob Shop',
        )
        self.assertIn('Bob Shop', str(platform_review2))

    def test_storefront_str(self):
        page = StorefrontPage.objects.create(tenant=self.tenant, slug='about', title='About', body='x')
        self.assertIn('about', str(page))

        locked_section = PageSection.objects.create(
            tenant=self.tenant, page_key='overview', lock_key='contact', section_type='locked',
        )
        self.assertIn('contact', str(locked_section))

        titled_section = PageSection.objects.create(
            tenant=self.tenant, page_key='overview', title='My Title', section_type='text',
        )
        self.assertIn('My Title', str(titled_section))

        bare_section = PageSection.objects.create(
            tenant=self.tenant, page_key='overview', section_type='spacer',
        )
        self.assertIn('spacer', str(bare_section))

        slide = HeroSlide.objects.create(tenant=self.tenant, order=1)
        self.assertIn('slide 1', str(slide))
