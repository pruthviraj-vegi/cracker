"""Tests for base/decorators.py: get_client_ip."""
from unittest.mock import MagicMock
from django.test import TestCase
from base.decorators import get_client_ip


class GetClientIPTests(TestCase):
    """Tests for get_client_ip()."""

    def test_remote_addr(self):
        request = MagicMock()
        request.META = {"REMOTE_ADDR": "192.168.1.1"}
        self.assertEqual(get_client_ip(request), "192.168.1.1")

    def test_x_forwarded_for(self):
        request = MagicMock()
        request.META = {
            "REMOTE_ADDR": "192.168.1.1",
            "HTTP_X_FORWARDED_FOR": "10.0.0.1, 10.0.0.2",
        }
        self.assertEqual(get_client_ip(request), "10.0.0.1")

    def test_x_forwarded_for_single_ip(self):
        request = MagicMock()
        request.META = {
            "REMOTE_ADDR": "192.168.1.1",
            "HTTP_X_FORWARDED_FOR": "10.0.0.1",
        }
        self.assertEqual(get_client_ip(request), "10.0.0.1")

    def test_no_remote_addr(self):
        request = MagicMock()
        request.META = {}
        self.assertIsNone(get_client_ip(request))
