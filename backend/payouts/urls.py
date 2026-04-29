from django.urls import path

from .views import MerchantBalanceView, MerchantBankAccountsView, MerchantLedgerView, PayoutListCreateView

urlpatterns = [
    path("merchant/balance", MerchantBalanceView.as_view(), name="merchant-balance"),
    path("merchant/ledger", MerchantLedgerView.as_view(), name="merchant-ledger"),
    path("merchant/bank-accounts", MerchantBankAccountsView.as_view(), name="merchant-bank-accounts"),
    path("payouts", PayoutListCreateView.as_view(), name="payout-list-create"),
]
