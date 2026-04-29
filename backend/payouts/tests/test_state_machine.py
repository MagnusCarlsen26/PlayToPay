from django.test import TestCase

from payouts.models import Payout
from payouts.services import InvalidPayoutTransition, assert_transition
from payouts.tests.test_helpers import create_merchant_with_balance


class StateMachineTests(TestCase):
    def setUp(self):
        self.merchant, self.bank_account = create_merchant_with_balance(amount_paise=10000)

    def test_completed_to_pending_is_rejected(self):
        with self.assertRaises(InvalidPayoutTransition):
            assert_transition(Payout.Status.COMPLETED, Payout.Status.PENDING)

    def test_failed_to_completed_is_rejected(self):
        with self.assertRaises(InvalidPayoutTransition):
            assert_transition(Payout.Status.FAILED, Payout.Status.COMPLETED)
