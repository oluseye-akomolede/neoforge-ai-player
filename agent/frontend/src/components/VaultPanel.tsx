import { useMemo, useState } from 'react'
import { useHoldings, useVaultStore, useVaultWithdraw } from '../hooks'

/**
 * Bot holdings: the 36 carried slots plus the unbounded vault behind them.
 * Carried is only the working set — overflow pages to the vault automatically,
 * and criteria/BUILD both count vault contents as real holdings.
 */
export default function VaultPanel({ selectedBot }: { selectedBot: string | null }) {
  const [rows, refresh] = useHoldings(selectedBot)
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const store = useVaultStore()
  const withdraw = useVaultWithdraw()

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(
      (r) => r.item.toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q),
    )
  }, [rows, filter])

  const carriedTotal = rows.reduce((n, r) => n + r.carried, 0)
  const vaultTotal = rows.reduce((n, r) => n + r.vault, 0)

  const act = async (fn: () => Promise<unknown>, key: string) => {
    setBusy(key)
    try {
      await fn()
      await refresh()
    } finally {
      setBusy(null)
    }
  }

  if (!selectedBot) {
    return (
      <div className="panel">
        <h3 className="text-mc-gold font-bold mb-2">Holdings</h3>
        <p className="text-xs text-mc-gray">Select a bot to view carried items and vault.</p>
      </div>
    )
  }

  return (
    <div className="panel">
      <div className="flex justify-between items-center mb-2">
        <h3 className="text-mc-gold font-bold">
          Holdings — <span className="text-mc-aqua">{selectedBot}</span>
        </h3>
        <span className="text-xs text-mc-gray">
          {carriedTotal} carried · <span className="text-mc-purple">{vaultTotal} vault</span>
        </span>
      </div>

      <div className="flex gap-2 mb-2">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search items…"
          className="flex-1 bg-mc-dark border border-mc-accent rounded px-2 py-1 text-xs text-white"
        />
        <button
          onClick={() => act(() => store(selectedBot), 'flush')}
          disabled={busy === 'flush'}
          title="Page all evictable carried items into the vault (keeps gear + food)"
          className="text-xs px-2 py-1 rounded bg-mc-accent hover:bg-mc-gold hover:text-mc-dark transition-colors disabled:opacity-50"
        >
          {busy === 'flush' ? '…' : 'Stow all'}
        </button>
      </div>

      {shown.length === 0 ? (
        <p className="text-xs text-mc-gray">{filter ? 'No matching items.' : 'Nothing held.'}</p>
      ) : (
        <div className="space-y-0.5 max-h-72 overflow-y-auto">
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-2 text-[10px] text-mc-gray px-1 sticky top-0 bg-mc-dark">
            <span>Item</span>
            <span className="text-right w-12">Carried</span>
            <span className="text-right w-12">Vault</span>
            <span className="w-16" />
          </div>
          {shown.map((r) => (
            <div
              key={r.item}
              className="grid grid-cols-[1fr_auto_auto_auto] gap-2 items-center text-xs px-1 py-0.5 rounded hover:bg-mc-accent/40"
            >
              <span className="truncate text-mc-gray" title={r.item}>
                {(r.name || r.item).replace('minecraft:', '')}
              </span>
              <span className="text-right w-12 text-white">{r.carried || '—'}</span>
              <span className="text-right w-12 text-mc-purple">{r.vault || '—'}</span>
              <span className="flex gap-1 w-16 justify-end">
                <button
                  onClick={() => act(() => store(selectedBot, r.item, r.carried), `s-${r.item}`)}
                  disabled={!r.carried || busy === `s-${r.item}`}
                  title="Store carried stock in the vault"
                  className="px-1 rounded bg-mc-accent hover:bg-mc-gold hover:text-mc-dark disabled:opacity-30"
                >
                  ↓
                </button>
                <button
                  onClick={() => act(() => withdraw(selectedBot, r.item, Math.min(r.vault, 64)), `w-${r.item}`)}
                  disabled={!r.vault || busy === `w-${r.item}`}
                  title="Withdraw up to 64 from the vault"
                  className="px-1 rounded bg-mc-accent hover:bg-mc-gold hover:text-mc-dark disabled:opacity-30"
                >
                  ↑
                </button>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
