import unittest
from urllib.parse import quote_plus

from src.services.cloudpayments_client import (
    build_cloudpayments_hmac,
    verify_cloudpayments_signature,
)
from src.services.payment_service import parse_rub_amount_text


class CloudPaymentsAmountParsingTests(unittest.TestCase):
    def test_accepts_integer_and_decimal_rub_amounts(self) -> None:
        self.assertEqual(str(parse_rub_amount_text("500")), "500.00")
        self.assertEqual(str(parse_rub_amount_text("1 499,90 ₽")), "1499.90")

    def test_rejects_invalid_rub_amounts(self) -> None:
        self.assertIsNone(parse_rub_amount_text("0"))
        self.assertIsNone(parse_rub_amount_text("-10"))
        self.assertIsNone(parse_rub_amount_text("сколько не жалко"))


class CloudPaymentsSignatureTests(unittest.TestCase):
    def test_accepts_content_hmac_for_raw_body(self) -> None:
        body = b"InvoiceId=sbp_123&AccountId=42&Amount=500.00"
        secret = "test-secret"
        headers = {"Content-HMAC": build_cloudpayments_hmac(body, secret)}

        self.assertTrue(
            verify_cloudpayments_signature(
                raw_body=body,
                headers=headers,
                secret=secret,
            )
        )

    def test_accepts_x_content_hmac_for_decoded_body(self) -> None:
        decoded = "Description=Оплата по СБП&InvoiceId=sbp_123"
        raw = f"Description={quote_plus('Оплата по СБП')}&InvoiceId=sbp_123".encode("utf-8")
        secret = "test-secret"
        headers = {"X-Content-HMAC": build_cloudpayments_hmac(decoded, secret)}

        self.assertTrue(
            verify_cloudpayments_signature(
                raw_body=raw,
                headers=headers,
                secret=secret,
            )
        )


if __name__ == "__main__":
    unittest.main()
