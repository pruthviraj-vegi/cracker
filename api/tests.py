import uuid
import hashlib
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from api.models import APIToken, APIRequestLog
from security.models import UnauthorizedAccess
from customer.models import Customer, CustomerCreditSummary

User = get_user_model()


class APITokenModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            first_name="Test",
            phone_number="1234567890",
            password="testpassword",
            email="test@example.com"
        )

    def test_token_generation_and_verification(self):
        expires_at = timezone.now() + timedelta(days=30)
        token_instance, raw_token = APIToken.generate(
            name="Test Token",
            purpose="Testing",
            expires_at=expires_at,
            created_by=self.user,
            allowed_ips=[]
        )

        self.assertEqual(token_instance.name, "Test Token")
        self.assertEqual(token_instance.prefix, raw_token[:8])
        
        # Verify hashing
        expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        self.assertEqual(token_instance.token_hash, expected_hash)

        # Verification via verify method
        verified = APIToken.verify(raw_token)
        self.assertEqual(verified, token_instance)

        # Verify failure with wrong token
        self.assertIsNone(APIToken.verify("wrongtoken"))

    def test_allowed_ips_validation(self):
        expires_at = timezone.now() + timedelta(days=30)
        token = APIToken(
            name="IP Token",
            expires_at=expires_at,
            created_by=self.user,
            allowed_ips=["192.168.1.1", "invalid-ip"]
        )

        with self.assertRaises(ValidationError) as ctx:
            token.full_clean()
        self.assertIn("allowed_ips", ctx.exception.message_dict)

        # Test valid IPs are cleaned and accepted
        token.allowed_ips = ["  192.168.1.1  ", "2001:db8::1"]
        token.full_clean()
        token.save()
        self.assertEqual(token.allowed_ips, ["192.168.1.1", "2001:db8::1"])


class APITokenViewsTests(TestCase):
    def setUp(self):
        self.user_no_perms = User.objects.create_user(
            first_name="No",
            phone_number="9876543210",
            password="password1",
            email="no@example.com"
        )
        self.user_with_perms = User.objects.create_user(
            first_name="With",
            phone_number="8765432109",
            password="password1",
            email="with@example.com"
        )
        
        # Assign permissions to user_with_perms
        perms = Permission.objects.filter(
            codename__in=["view_apitoken", "add_apitoken", "change_apitoken"],
            content_type__app_label="api"
        )
        self.user_with_perms.user_permissions.add(*perms)

        # Create a sample token for detail/revoke testing
        expires_at = timezone.now() + timedelta(days=30)
        self.token, _ = APIToken.generate(
            name="Sample Token",
            purpose="Sample",
            expires_at=expires_at,
            created_by=self.user_with_perms
        )

    def test_management_views_require_permissions(self):
        # 1. Unauthenticated user gets redirected to login because of CustomLoginRequiredMiddleware
        response = self.client.get(reverse("api_tokens:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

        # 2. Authenticated user without permissions gets 403 Forbidden
        self.client.login(phone_number="9876543210", password="password1")
        response = self.client.get(reverse("api_tokens:home"))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("api_tokens:fetch"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("api_tokens:create"), {"name": "Test"})
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("api_tokens:detail", kwargs={"pk": self.token.pk}))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("api_tokens:revoke", kwargs={"pk": self.token.pk}))
        self.assertEqual(response.status_code, 403)

    def test_management_views_with_permissions(self):
        self.client.login(phone_number="8765432109", password="password1")

        # View home
        response = self.client.get(reverse("api_tokens:home"))
        self.assertEqual(response.status_code, 200)

        # Fetch list
        response = self.client.get(reverse("api_tokens:fetch"))
        self.assertEqual(response.status_code, 200)

        # Detail view
        response = self.client.get(reverse("api_tokens:detail", kwargs={"pk": self.token.pk}))
        self.assertEqual(response.status_code, 200)

        # Create token
        response = self.client.post(
            reverse("api_tokens:create"),
            {"name": "New Token", "purpose": "Testing Views", "expires_in": "90"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("raw_token", data)

        # Revoke token
        response = self.client.post(reverse("api_tokens:revoke", kwargs={"pk": self.token.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        # Check token is revoked
        self.token.refresh_from_db()
        self.assertFalse(self.token.is_active)
        self.assertIsNotNone(self.token.revoked_at)
        self.assertEqual(self.token.revoked_by, self.user_with_perms)


class APITokenMiddlewareTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            first_name="API",
            phone_number="1234567890",
            password="password1",
            email="api@example.com"
        )
        self.customer = Customer.objects.create(
            name="API Customer",
            phone_number="9999999999",
            created_by=self.user
        )
        
        # Get or update the automatically created credit summary
        summary, created = CustomerCreditSummary.objects.get_or_create(customer=self.customer)
        summary.balance_amount = 150.00
        summary.save()

        # Create tokens
        self.active_token_instance, self.active_raw_token = APIToken.generate(
            name="Active Token",
            purpose="Verify",
            expires_at=timezone.now() + timedelta(days=1),
            created_by=self.user
        )

        self.revoked_token_instance, self.revoked_raw_token = APIToken.generate(
            name="Revoked Token",
            purpose="Verify",
            expires_at=timezone.now() + timedelta(days=1),
            created_by=self.user
        )
        self.revoked_token_instance.is_active = False
        self.revoked_token_instance.save()

        self.expired_token_instance, self.expired_raw_token = APIToken.generate(
            name="Expired Token",
            purpose="Verify",
            expires_at=timezone.now() - timedelta(days=1),
            created_by=self.user
        )

        self.ip_token_instance, self.ip_raw_token = APIToken.generate(
            name="IP Token",
            purpose="Verify",
            expires_at=timezone.now() + timedelta(days=1),
            created_by=self.user,
            allowed_ips=["192.168.1.50"]
        )

    def test_missing_or_invalid_header_format(self):
        # 1. No Authorization header
        response = self.client.get(reverse("api:balance"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Authorization header missing or invalid")
        
        # Verify global UnauthorizedAccess log
        self.assertTrue(UnauthorizedAccess.objects.filter(required_roles="bearer_auth_header").exists())

        # 2. Invalid header format
        response = self.client.get(
            reverse("api:balance"),
            HTTP_AUTHORIZATION="Bearer"
        )
        self.assertEqual(response.status_code, 403)

    def test_invalid_token(self):
        response = self.client.get(
            reverse("api:balance"),
            HTTP_AUTHORIZATION="Bearer invalidtokenhash12345"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Invalid token")
        
        # Verify global UnauthorizedAccess log
        self.assertTrue(UnauthorizedAccess.objects.filter(required_roles="valid_api_token").exists())

    def test_revoked_token(self):
        response = self.client.get(
            reverse("api:balance"),
            HTTP_AUTHORIZATION=f"Bearer {self.revoked_raw_token}"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Token has been revoked")

        # Verify failure is logged in token's APIRequestLog
        self.assertTrue(APIRequestLog.objects.filter(token=self.revoked_token_instance, response_status=403).exists())

    def test_expired_token(self):
        response = self.client.get(
            reverse("api:balance"),
            HTTP_AUTHORIZATION=f"Bearer {self.expired_raw_token}"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Token has expired")

        # Verify failure is logged in token's APIRequestLog
        self.assertTrue(APIRequestLog.objects.filter(token=self.expired_token_instance, response_status=403).exists())

    def test_ip_address_mismatch(self):
        # Mismatched IP
        response = self.client.get(
            reverse("api:balance"),
            HTTP_AUTHORIZATION=f"Bearer {self.ip_raw_token}",
            REMOTE_ADDR="192.168.1.100"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "IP address not allowed")

        # Logged
        self.assertTrue(APIRequestLog.objects.filter(token=self.ip_token_instance, response_status=403).exists())

        # Matched IP
        response = self.client.post(
            reverse("api:balance"),
            {"phone_number": "9999999999"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.ip_raw_token}",
            REMOTE_ADDR="192.168.1.50"
        )
        self.assertEqual(response.status_code, 200)

    def test_successful_request(self):
        response = self.client.post(
            reverse("api:balance"),
            {"phone_number": "9999999999"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.active_raw_token}"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(float(data["payload"]["attributes"]["balance"]), 150.00)
        self.assertEqual(data["recipient"]["name"], "Api Customer")

        # Verify usage details updated
        self.active_token_instance.refresh_from_db()
        self.assertIsNotNone(self.active_token_instance.last_used_at)
        self.assertEqual(self.active_token_instance.last_used_ip, "127.0.0.1")

        # Verify APIRequestLog has success code 200
        log = APIRequestLog.objects.filter(token=self.active_token_instance).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.response_status, 200)
        self.assertEqual(log.endpoint, reverse("api:balance"))
        self.assertEqual(log.method, "POST")
