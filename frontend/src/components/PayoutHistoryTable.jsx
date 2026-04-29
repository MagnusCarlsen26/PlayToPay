const STATUS_CLASS_MAP = {
  pending: "bg-amber-500/15 text-amber-200",
  processing: "bg-sky-500/15 text-sky-200",
  completed: "bg-emerald-500/15 text-emerald-200",
  failed: "bg-rose-500/15 text-rose-200",
};

function formatMoney(paise) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format((paise || 0) / 100);
}

export default function PayoutHistoryTable({ payouts }) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur-sm">
      <h2 className="font-display text-2xl text-sand">Payout history</h2>
      <div className="mt-4 overflow-x-auto">
        <table className="min-w-full text-left text-sm text-steel">
          <thead>
            <tr className="border-b border-white/10">
              <th className="pb-3 pr-4">Amount</th>
              <th className="pb-3 pr-4">Status</th>
              <th className="pb-3 pr-4">Attempts</th>
              <th className="pb-3 pr-4">Requested</th>
              <th className="pb-3 pr-4">Updated</th>
            </tr>
          </thead>
          <tbody>
            {payouts.map((payout) => (
              <tr key={payout.id} className="border-b border-white/5">
                <td className="py-3 pr-4 text-sand">{formatMoney(payout.amount_paise)}</td>
                <td className="py-3 pr-4">
                  <span className={`rounded-full px-3 py-1 text-xs font-semibold ${STATUS_CLASS_MAP[payout.status]}`}>
                    {payout.status}
                  </span>
                </td>
                <td className="py-3 pr-4">{payout.attempt_count}</td>
                <td className="py-3 pr-4">{new Date(payout.created_at).toLocaleString()}</td>
                <td className="py-3 pr-4">{new Date(payout.updated_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
