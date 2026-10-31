"""Tests for remembered account (password-only) login functionality in base app."""

from django.test import TestCase, Client
from django.urls import reverse
from user.models import CustomUser


class RememberedAccountLoginTests(TestCase):
    """Test suite for trusted device remembered account login."""

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            phone_number="9876543210",
            first_name="Raju",
            last_name="Varma",
            password="securepassword123",
        )

    def test_login_with_remember_sets_signed_cookie(self):
        """Successful login with remember=True sets a signed remembered_account cookie."""
        response = self.client.post(
            reverse("base:login"),
            {
                "username": "9876543210",
                "password": "securepassword123",
                "remember": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("remembered_account", response.cookies)
        cookie_val = response.cookies["remembered_account"].value
        self.assertTrue(len(cookie_val) > 0)

    def test_login_without_remember_clears_cookie(self):
        """Successful login with remember unchecked deletes any existing cookie."""
        # Pre-set cookie
        self.client.cookies["remembered_account"] = "dummy-cookie"
        response = self.client.post(
            reverse("base:login"),
            {
                "username": "9876543210",
                "password": "securepassword123",
                # remember omitted/unchecked
            },
        )
        self.assertEqual(response.status_code, 302)
        # Check that cookie is deleted / expired
        self.assertEqual(response.cookies["remembered_account"].value, "")

    def test_get_login_page_with_remembered_cookie_shows_welcome_back(self):
        """GET /login/ with valid cookie renders password-only remembered view."""
        # First log in with remember=True
        self.client.post(
            reverse("base:login"),
            {
                "username": "9876543210",
                "password": "securepassword123",
                "remember": "on",
            },
        )
        # Log out (session cleared, cookie preserved)
        self.client.get(reverse("base:logout"))

        # Visit login page again
        response = self.client.get(reverse("base:login"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["remembered_user"])
        self.assertEqual(response.context["remembered_user"]["full_name"], "Raju Varma")
        self.assertEqual(response.context["remembered_user"]["masked_phone"], "•••••• 3210")
        self.assertContains(response, "Welcome Back")
        self.assertContains(response, "Raju Varma")
        self.assertContains(response, "•••••• 3210")
        self.assertContains(response, "Sign In as Raju")

    def test_get_login_with_switch_param(self):
        """GET /login/?switch=1 sets switch_account in context."""
        self.client.post(
            reverse("base:login"),
            {
                "username": "9876543210",
                "password": "securepassword123",
                "remember": "on",
            },
        )
        self.client.get(reverse("base:logout"))

        response = self.client.get(reverse("base:login") + "?switch=1")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["switch_account"])

    def test_forget_account_view(self):
        """Calling forget_account deletes the cookie and redirects to login."""
        self.client.post(
            reverse("base:login"),
            {
                "username": "9876543210",
                "password": "securepassword123",
                "remember": "on",
            },
        )
        self.client.get(reverse("base:logout"))

        response = self.client.get(reverse("base:forget_account"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("base:login"))
        self.assertEqual(response.cookies["remembered_account"].value, "")

    def test_deactivated_user_cookie_ignored(self):
        """If user is deactivated, remembered cookie is ignored."""
        self.client.post(
            reverse("base:login"),
            {
                "username": "9876543210",
                "password": "securepassword123",
                "remember": "on",
            },
        )
        self.client.get(reverse("base:logout"))

        # Deactivate user
        self.user.is_active = False
        self.user.save()

        response = self.client.get(reverse("base:login"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["remembered_user"])
