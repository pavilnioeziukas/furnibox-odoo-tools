import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.odoo_client import OdooClient, OdooReadOnlyError


class OdooClientTests(unittest.TestCase):
    def setUp(self):
        config = SimpleNamespace(
            url="https://odoo.example.test",
            database="test",
            username="reader@example.test",
            api_key="secret",
        )
        self.client = OdooClient(config)
        self.client.uid = 7
        self.client.models = Mock()
        self.client.models.execute_kw.return_value = [{"id": 1}]

    def test_supported_read_methods_reach_xmlrpc(self):
        for method in sorted(OdooClient.ALLOWED_METHODS):
            with self.subTest(method=method):
                self.client.execute("res.partner", method)

        called_methods = {
            call.args[4] for call in self.client.models.execute_kw.call_args_list
        }
        self.assertEqual(called_methods, set(OdooClient.ALLOWED_METHODS))

    def test_write_methods_are_blocked_before_xmlrpc(self):
        for method in ("create", "write", "unlink"):
            with self.subTest(method=method):
                with self.assertRaisesRegex(OdooReadOnlyError, method):
                    self.client.execute("res.partner", method)

        self.client.models.execute_kw.assert_not_called()

    def test_unknown_method_is_blocked_before_xmlrpc(self):
        with self.assertRaises(OdooReadOnlyError):
            self.client.execute("res.partner", "action_confirm")

        self.client.models.execute_kw.assert_not_called()

    def test_public_write_helpers_do_not_exist(self):
        for method in ("create", "write", "unlink"):
            with self.subTest(method=method):
                self.assertFalse(hasattr(self.client, method))


if __name__ == "__main__":
    unittest.main()
