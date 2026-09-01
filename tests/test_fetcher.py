"""Tests for fetcher internals — especially the credential-redaction guard."""

import os
import unittest

from terminal_zero import sources
from terminal_zero.edgar import fetcher


class RedactSecret(unittest.TestCase):
    def setUp(self):
        self.source = sources.Source(
            key="test", hosts=("x",), requests_per_second=1.0,
            licence_class="x", docs="", auth="query_param",
            auth_env="TZ_TEST_KEY", auth_param="key",
        )
        os.environ["TZ_TEST_KEY"] = "SUPERSECRET123"

    def tearDown(self):
        os.environ.pop("TZ_TEST_KEY", None)

    def test_key_is_redacted_from_body(self):
        body = b'{"UserID":"SUPERSECRET123","Data":[1,2,3]}'
        out = fetcher._redact_secret(body, self.source)
        self.assertNotIn(b"SUPERSECRET123", out)
        self.assertIn(b"<REDACTED>", out)
        self.assertIn(b'"Data":[1,2,3]', out)  # data untouched

    def test_no_env_no_change(self):
        os.environ.pop("TZ_TEST_KEY", None)
        body = b'{"UserID":"SUPERSECRET123"}'
        self.assertEqual(fetcher._redact_secret(body, self.source), body)

    def test_source_without_auth_env_unchanged(self):
        s = sources.Source(key="n", hosts=("y",), requests_per_second=1.0,
                           licence_class="x", docs="", auth="none")
        body = b"anything"
        self.assertEqual(fetcher._redact_secret(body, s), body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
