from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .selectors import get_merchant_balance, get_merchant_bank_accounts, get_merchant_ledger, get_merchant_payouts
from .serializers import BankAccountSerializer, LedgerEntrySerializer, MerchantBalanceSerializer, PayoutRequestSerializer, PayoutSerializer
from .services import PayoutError, get_merchant_from_header, request_payout


class MerchantScopedAPIView(APIView):
    merchant = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        try:
            self.merchant = get_merchant_from_header(request.headers.get("X-Merchant-Id"))
        except PayoutError as exc:
            raise ValidationError(exc.as_response())


class MerchantBalanceView(MerchantScopedAPIView):
    def get(self, request):
        serializer = MerchantBalanceSerializer(get_merchant_balance(self.merchant))
        return Response(serializer.data)


class MerchantLedgerView(MerchantScopedAPIView):
    def get(self, request):
        limit = min(int(request.query_params.get("limit", 20)), 100)
        queryset = get_merchant_ledger(self.merchant)[:limit]
        return Response({"results": LedgerEntrySerializer(queryset, many=True).data})


class MerchantBankAccountsView(MerchantScopedAPIView):
    def get(self, request):
        queryset = get_merchant_bank_accounts(self.merchant)
        return Response({"results": BankAccountSerializer(queryset, many=True).data})


class PayoutListCreateView(MerchantScopedAPIView):
    def get(self, request):
        queryset = get_merchant_payouts(self.merchant)
        return Response({"results": PayoutSerializer(queryset, many=True).data})

    def post(self, request):
        serializer = PayoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        idempotency_key = request.headers.get("Idempotency-Key")
        try:
            response = request_payout(
                merchant=self.merchant,
                idempotency_key=idempotency_key,
                amount_paise=serializer.validated_data["amount_paise"],
                bank_account_id=serializer.validated_data["bank_account_id"],
                request_method=request.method,
                request_path=request.path,
            )
        except PayoutError as exc:
            return Response(exc.as_response(), status=exc.status_code)
        return Response(response.body, status=response.status_code)
