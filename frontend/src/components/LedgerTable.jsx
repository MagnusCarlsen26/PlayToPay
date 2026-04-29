function formatMoney(paise) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format((paise || 0) / 100);
}

export default function LedgerTable({ entries }) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur-sm">
      <h2 className="font-display text-2xl text-sand">Recent ledger</h2>
      <div className="mt-4 space-y-3">
        {entries.map((entry) => (
          <div key={entry.id} className="flex items-center justify-between rounded-2xl border border-white/5 bg-black/10 px-4 py-3">
            <div>
              <div className="text-sm font-semibold capitalize text-sand">{entry.entry_type.replaceAll("_", " ")}</div>
              <div className="text-xs text-steel">{entry.reference || "Ledger event"} • {new Date(entry.created_at).toLocaleString()}</div>
            </div>
            <div className={`font-semibold ${entry.amount_paise < 0 ? "text-rose-300" : "text-emerald-300"}`}>
              {formatMoney(entry.amount_paise)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
