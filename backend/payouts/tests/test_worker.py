from datetime import timedelta

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from payouts.models import LedgerEntry, MerchantBalance, Payout
from payouts.tasks import process_payouts_batch
from payouts.tests.test_helpers import create_merchant_with_balance


class WorkerTests(TestCase):
    def setUp(self):
        self.merchant, self.bank_account = create_merchant_with_balance(amount_paise=10000)

    def create_processing_payout(self, *, attempt_count: int):
        balance = MerchantBalance.objects.get(merchant=self.merchant)
        balance.available_balance_paise -= 6000
        balance.held_balance_paise += 6000
        balance.save(update_fields=["available_balance_paise", "held_balance_paise"])
        payout = Payout.objects.create(
            merchant=self.merchant,
            bank_account=self.bank_account,
            amount_paise=6000,
            status=Payout.Status.PROCESSING,
            attempt_count=attempt_count,
            next_retry_at=timezone.now() - timedelta(seconds=1),
            last_attempted_at=timezone.now() - timedelta(minutes=1),
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.PAYOUT_HOLD,
            amount_paise=-6000,
            payout=payout,
            reference="hold:test",
        )
        return payout

    @patch("payouts.tasks.simulate_bank_settlement", return_value="hang")
    def test_hang_keeps_processing_before_max_attempts(self, _mock_result):
        payout = self.create_processing_payout(attempt_count=1)
        process_payouts_batch()

        payout.refresh_from_db()
        balance = MerchantBalance.objects.get(merchant=self.merchant)
        self.assertEqual(payout.status, Payout.Status.PROCESSING)
        self.assertEqual(payout.attempt_count, 2)
        self.assertEqual(balance.available_balance_paise, 4000)
        self.assertEqual(balance.held_balance_paise, 6000)

    @patch("payouts.tasks.simulate_bank_settlement", return_value="hang")
    def test_hang_fails_after_max_attempts_and_releases_funds(self, _mock_result):
        payout = self.create_processing_payout(attempt_count=2)
        process_payouts_batch()

        payout.refresh_from_db()
        balance = MerchantBalance.objects.get(merchant=self.merchant)
        self.assertEqual(payout.status, Payout.Status.FAILED)
        self.assertEqual(balance.available_balance_paise, 10000)
        self.assertEqual(balance.held_balance_paise, 0)
        self.assertTrue(
            LedgerEntry.objects.filter(
                payout=payout,
                entry_type=LedgerEntry.EntryType.PAYOUT_RELEASE,
                amount_paise=6000,
            ).exists()
        )
