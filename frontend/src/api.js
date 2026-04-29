const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";
const MERCHANT_ID = import.meta.env.VITE_DEMO_MERCHANT_ID || "";

function buildHeaders(extraHeaders = {}) {
  return {
    "Content-Type": "application/json",
    "X-Merchant-Id": MERCHANT_ID,
    ...extraHeaders,
  };
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: buildHeaders(options.headers),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || "Request failed");
  }
  return data;
}

export function fetchBalance() {
  return request("/merchant/balance");
}

export function fetchLedger() {
  return request("/merchant/ledger?limit=20");
}

export function fetchPayouts() {
  return request("/payouts");
}

export function fetchBankAccounts() {
  return request("/merchant/bank-accounts");
}

export function createPayout({ amount_paise, bank_account_id, idempotencyKey }) {
  return request("/payouts", {
    method: "POST",
    headers: {
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({ amount_paise, bank_account_id }),
  });
}
