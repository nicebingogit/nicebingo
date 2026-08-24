import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { playClick } from '../sound.js';

const TX_STATUS = {
  pending: { label: '⏳ Pending', cls: 'pending' },
  approved: { label: '✅ Approved', cls: 'approved' },
  rejected: { label: '❌ Rejected', cls: 'rejected' },
};

const PROVIDER_SUGGESTIONS_DEFAULT = ['TeleBirr', 'CBE', 'CBB', 'Bank', 'Other'];

export default function AdminPanel({ room, onError, onChanged }) {
  const [tab, setTab] = useState('users');
  const [stats, setStats] = useState(null);
  const [bots, setBots] = useState(null);
  const [users, setUsers] = useState([]);
  const [txs, setTxs] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [providers, setProviders] = useState([]);
  const [flash, setFlash] = useState('');

  // user detail modal (click a row to open it)
  const [selected, setSelected] = useState(null);
  const [editAmt, setEditAmt] = useState('');
  const [detailMsg, setDetailMsg] = useState('');

  // payment account form
  const [accForm, setAccForm] = useState({ provider: '', account_name: '', account_number: '', is_active: true });
  const [editingAcc, setEditingAcc] = useState(null);
  const [confirmDelAcc, setConfirmDelAcc] = useState(null);

  // inline two-step delete confirm (window.confirm is unreliable in WebViews)
  const [confirmDel, setConfirmDel] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [s, b] = await Promise.all([api.admin.stats(), api.admin.bots()]);
      setStats(s.stats);
      setBots(b);
    } catch (e) {
      onError?.(e.message);
    }
  }, [onError]);

  const loadUsers = useCallback(async () => {
    try {
      const d = await api.admin.users();
      setUsers(d.users || []);
    } catch (e) {
      onError?.(e.message);
    }
  }, [onError]);

  const loadTxs = useCallback(async () => {
    try {
      const d = await api.admin.transactions();
      setTxs(d.transactions || []);
    } catch (e) {
      onError?.(e.message);
    }
  }, [onError]);

  const loadAccounts = useCallback(async () => {
    try {
      const d = await api.admin.accounts();
      setAccounts(d.accounts || []);
    } catch (e) {
      onError?.(e.message);
    }
  }, [onError]);

  const loadProviders = useCallback(async () => {
    try {
      const d = await api.admin.providers();
      setProviders(d.providers || []);
    } catch (e) {
      // silently fall back to default suggestions
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { if (tab === 'users') loadUsers(); }, [tab, loadUsers]);
  useEffect(() => { if (tab === 'transactions') loadTxs(); }, [tab, loadTxs]);
  useEffect(() => { if (tab === 'accounts') { loadAccounts(); loadProviders(); } }, [tab, loadAccounts, loadProviders]);

  const act = async (fn, okMsg) => {
    playClick();
    setFlash('…');
    try {
      const r = await fn();
      setFlash(okMsg + (r.added !== undefined ? ` (+${r.added})` : ''));
      await refresh();
    } catch (e) {
      setFlash(`❌ ${e.message}`);
    }
    setTimeout(() => setFlash(''), 2500);
  };

  // -------------------------------------------------- credit editing (target)
  const adjustCredit = async (delta) => {
    if (!selected) return;
    playClick();
    try {
      // the server applies the amount to `user_id` (the SELECTED user) — the
      // logged-in admin's own balance is never touched
      await api.admin.credit(selected.user_id, delta);
      await loadUsers();
      onChanged?.();
      // refresh the open detail panel with the fresh numbers
      const d = await api.admin.users();
      setSelected(d.users.find((u) => u.user_id === selected.user_id) || null);
      setDetailMsg(`✅ ${delta > 0 ? '+' : ''}${delta} ${delta > 0 ? 'added to' : 'taken from'} ${selected.full_name || `#${selected.user_id}`}`);
      setTimeout(() => setDetailMsg(''), 3000);
      setEditAmt('');
    } catch (err) {
      setDetailMsg(`❌ ${err.message}`);
    }
  };

  const deleteUser = async (target) => {
    playClick();
    setConfirmDel(null);
    try {
      await api.admin.deleteUser(target);
      if (selected?.user_id === target) setSelected(null);
      await loadUsers();
      onChanged?.();
    } catch (err) {
      onError?.(err.message);
    }
  };

  const review = async (id, action) => {
    playClick();
    try {
      await api.admin.reviewTransaction(id, action);
      await loadTxs();
      onChanged?.(); // user balance may have changed (approve moves money)
    } catch (err) {
      onError?.(err.message);
    }
  };

  // ------------------------------------------------------- payment accounts
  const saveAccount = async (e) => {
    e.preventDefault();
    playClick();
    try {
      if (editingAcc) {
        await api.admin.updateAccount({ id: editingAcc, ...accForm });
      } else {
        await api.admin.addAccount(accForm);
      }
      setAccForm({ provider: '', account_name: '', account_number: '', is_active: true });
      setEditingAcc(null);
      setFlash('✅ Payment account saved.');
      setTimeout(() => setFlash(''), 3000);
      await loadAccounts();
      onChanged?.(); // users' wallet view refreshes
    } catch (err) {
      onError?.(err.message);
    }
  };

  const toggleAccount = async (a) => {
    playClick();
    try {
      await api.admin.updateAccount({ id: a.id, is_active: !a.is_active });
      await loadAccounts();
      onChanged?.();
    } catch (err) {
      onError?.(err.message);
    }
  };

  const editAccount = (a) => {
    playClick();
    setEditingAcc(a.id);
    setAccForm({
      provider: a.provider,
      account_name: a.account_name,
      account_number: a.account_number,
      is_active: a.is_active,
    });
  };

  const deleteAccount = async (id) => {
    playClick();
    setConfirmDelAcc(null);
    try {
      await api.admin.deleteAccount(id);
      await loadAccounts();
      onChanged?.();
    } catch (err) {
      onError?.(err.message);
    }
  };

  const openUser = (u) => {
    playClick();
    setSelected(u);
    setEditAmt('');
    setDetailMsg('');
  };

  const pendingCount = txs.filter((t) => t.status === 'pending').length;

  return (
    <div className="panel admin-panel">
      <div className="picker-title">🛠 Admin controls</div>

      <div className="settings-tabs">
        {[
          ['users', '👥 Users'],
          ['transactions', '🧾 Wallet'],
          ['accounts', '💳 Accounts'],
        ].map(([id, label]) => (
          <button
            key={id}
            className={`settings-tab ${tab === id ? 'active' : ''}`}
            onClick={() => { playClick(); setTab(id); }}
          >
            {label}
          </button>
        ))}
      </div>

      {flash && <div className="admin-flash">{flash}</div>}

      {/* ----------------------------------------------------------- USERS */}
      {tab === 'users' && (
        <div className="users-tab">
          <p className="reg-hint">
            Tap a user to open their profile — edit <b>their</b> credit there
            (your own balance is never affected).
          </p>
          <div className="user-list">
            {users.map((u) => (
              <button
                key={u.user_id}
                className={`user-row clickable ${u.is_registered ? '' : 'unreg'}`}
                onClick={() => openUser(u)}
              >
                <div className="user-info">
                  <div className="user-name">
                    {u.full_name || u.username || `User #${u.user_id}`}
                    {!u.is_registered && <span className="user-badge">unregistered</span>}
                  </div>
                  <div className="user-meta">
                    id {u.user_id} · {u.phone || 'no phone'} · {u.rounds ?? 0} rounds · {u.wins ?? 0} wins
                  </div>
                </div>
                <div className="user-credit">
                  <b className="gold">{u.credit} ETB</b>
                  <span className="user-btn hint">Details ›</span>
                </div>
              </button>
            ))}
            {users.length === 0 && <div className="muted">No users yet.</div>}
          </div>
        </div>
      )}

      {/* ----------------------------------------------------- TRANSACTIONS */}
      {tab === 'transactions' && (
        <div className="tx-admin">
          {pendingCount > 0 && (
            <div className="admin-flash" style={{ color: 'var(--gold)' }}>
              🔔 {pendingCount} pending request(s)
            </div>
          )}
          {txs.length === 0 && <div className="muted">No wallet requests yet.</div>}
          {txs.map((t) => {
            const st = TX_STATUS[t.status] || TX_STATUS.pending;
            return (
              <div key={t.id} className={`tx-row ${st.cls}`}>
                <div className="tx-main">
                  <span className="tx-type">{t.type === 'deposit' ? '⬇️ Deposit' : '⬆️ Withdraw'}</span>
                  <span className="tx-amount">{t.amount} ETB</span>
                  <span className="tx-meta">
                    <b>{t.user_name || `#${t.user_id}`}</b>
                    {t.phone ? ` · ${t.phone}` : ''}
                    {/* deposits show the admin account paid into; withdrawals
                        show the destination account the user provided */}
                    {t.provider
                      ? ` · ${t.provider}${t.account_holder ? ` / ${t.account_holder}` : ''} ${t.account_number ? `(${t.account_number})` : ''}`
                      : ''}
                    {t.tx_id ? ` · Ref ${t.tx_id}` : ''} · {t.created_at?.slice(0, 16)}
                    {t.status !== 'pending' ? ` · reviewed ${t.reviewed_at?.slice(0, 16)}` : ''}
                  </span>
                </div>
                <div className="tx-actions">
                  <span className="tx-status">{st.label}</span>
                  {t.status === 'pending' && (
                    <>
                      <button className="btn btn-ghost user-btn" onClick={() => review(t.id, 'approve')}>✓ Approve</button>
                      <button className="btn btn-ghost user-btn danger" onClick={() => review(t.id, 'reject')}>✕ Reject</button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ---------------------------------------------------------- ACCOUNTS */}
      {tab === 'accounts' && (
        <div className="account-tab">
          <p className="reg-hint">
            Add the payment accounts players can deposit into (TeleBirr / CBE /
            CBB / bank…). Active accounts appear in every user's Settings →
            Wallet. Editing or deleting an account never changes past
            transactions (they keep a snapshot).
          </p>

          <div className="acc-admin-list">
            {accounts.map((a) => (
              <div key={a.id} className={`acc-admin-row ${a.is_active ? '' : 'off'}`}>
                <div className="user-info">
                  <div className="user-name">
                    {a.provider} <span className="muted">— {a.account_name}</span>
                    <span className={`user-badge ${a.is_active ? 'on' : ''}`}>
                      {a.is_active ? 'active' : 'inactive'}
                    </span>
                  </div>
                  <div className="user-meta">{a.account_number} · added {a.created_at?.slice(0, 10)}</div>
                </div>
                <div className="user-credit">
                  <button className="btn btn-ghost user-btn" onClick={() => editAccount(a)}>✏️ Edit</button>
                  <button className="btn btn-ghost user-btn" onClick={() => toggleAccount(a)}>
                    {a.is_active ? '🔕 Deactivate' : '🔊 Activate'}
                  </button>
                  <button
                    className="btn btn-ghost user-btn danger"
                    onClick={() => { playClick(); setConfirmDelAcc(confirmDelAcc === a.id ? null : a.id); }}
                  >
                    🗑
                  </button>
                </div>
                {confirmDelAcc === a.id && (
                  <div className="del-confirm">
                    <span className="muted">Delete the {a.provider} account {a.account_number}? Past transactions keep their snapshot.</span>
                    <button className="btn btn-danger user-btn" onClick={() => deleteAccount(a.id)}>Yes, delete</button>
                    <button className="btn btn-ghost user-btn" onClick={() => { playClick(); setConfirmDelAcc(null); }}>Cancel</button>
                  </div>
                )}
              </div>
            ))}
            {accounts.length === 0 && <div className="muted">No payment accounts yet — add one below.</div>}
          </div>

          <form className="credit-form acc-form" onSubmit={saveAccount}>
            <input
              type="text"
              list="provider-list"
              placeholder="Provider (TeleBirr, CBE, CBB…)"
              value={accForm.provider}
              onChange={(e) => setAccForm({ ...accForm, provider: e.target.value })}
              required
            />
            <datalist id="provider-list">
              {[...new Set([...providers, ...PROVIDER_SUGGESTIONS_DEFAULT])].map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>
            <input
              type="text"
              placeholder="Account holder (e.g. ELCOTECH)"
              value={accForm.account_name}
              onChange={(e) => setAccForm({ ...accForm, account_name: e.target.value })}
              required
            />
            <input
              type="text"
              placeholder="Account number"
              value={accForm.account_number}
              onChange={(e) => setAccForm({ ...accForm, account_number: e.target.value })}
              required
            />
            <label className="acc-active-check">
              <input
                type="checkbox"
                checked={accForm.is_active}
                onChange={(e) => setAccForm({ ...accForm, is_active: e.target.checked })}
              />
              Active
            </label>
            <button className="btn btn-primary" type="submit">
              {editingAcc ? '💾 Save changes' : '➕ Add account'}
            </button>
            {editingAcc && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => { playClick(); setEditingAcc(null); setAccForm({ provider: '', account_name: '', account_number: '', is_active: true }); }}
              >
                Cancel
              </button>
            )}
          </form>
        </div>
      )}

      {/* ------------------------------------------------ USER DETAIL MODAL */}
      {selected && (
        <div className="modal-overlay" onClick={() => setSelected(null)}>
          <div className="user-detail" onClick={(e) => e.stopPropagation()}>
            <div className="settings-head">
              <div className="picker-title">👤 {selected.full_name || selected.username || `User #${selected.user_id}`}</div>
              <button className="chip chip-btn" onClick={() => { playClick(); setSelected(null); }}>✕</button>
            </div>

            <div className="detail-grid">
              <div className="profile-row"><span className="muted">Full name</span><b>{selected.full_name || '—'}</b></div>
              <div className="profile-row"><span className="muted">Telegram username</span><b>@{selected.username || '—'}</b></div>
              <div className="profile-row"><span className="muted">Telegram ID</span><b>{selected.user_id}</b></div>
              <div className="profile-row"><span className="muted">Phone</span><b>{selected.phone || '—'}</b></div>
              <div className="profile-row"><span className="muted">Registration</span><b>{selected.is_registered ? '✅ Registered' : '⏳ Unregistered'}</b></div>
              <div className="profile-row"><span className="muted">Rounds played</span><b>{selected.rounds ?? 0}</b></div>
              <div className="profile-row"><span className="muted">Wins</span><b>{selected.wins ?? 0}</b></div>
              <div className="profile-row"><span className="muted">Total winnings</span><b className="gold">{selected.total_winnings ?? 0} ETB</b></div>
              <div className="profile-row"><span className="muted">Account created</span><b>{selected.created_at?.slice(0, 10) || '—'}</b></div>
            </div>

            <div className="credit-edit">
              <div className="wallet-form-title">
                💰 Credit: <b className="gold">{selected.credit} ETB</b>
              </div>
              <div className="wallet-form-row">
                <input
                  type="number" min="1" placeholder="amount"
                  value={editAmt} onChange={(e) => setEditAmt(e.target.value)}
                />
                <button
                  className="btn btn-ghost"
                  disabled={!Number(editAmt)}
                  onClick={() => adjustCredit(Number(editAmt))}
                >
                  ＋ Add
                </button>
                <button
                  className="btn btn-ghost"
                  disabled={!Number(editAmt)}
                  onClick={() => adjustCredit(-Number(editAmt))}
                >
                  − Subtract
                </button>
              </div>
              {detailMsg && <div className="admin-flash">{detailMsg}</div>}
              <p className="reg-hint">
                Only <b>{selected.full_name || `#${selected.user_id}`}</b>'s
                credit changes — the logged-in admin's balance stays the same.
              </p>
            </div>

            <div className="danger-zone">
              {confirmDel === selected.user_id ? (
                <div className="danger-confirm">
                  <p className="reg-hint">Delete this account entirely? This cannot be undone.</p>
                  <div className="wallet-form-row">
                    <button className="btn btn-danger" onClick={() => deleteUser(selected.user_id)}>Yes, delete</button>
                    <button className="btn btn-ghost" onClick={() => { playClick(); setConfirmDel(null); }}>Cancel</button>
                  </div>
                </div>
              ) : (
                <button className="btn btn-danger" onClick={() => { playClick(); setConfirmDel(selected.user_id); }}>
                  🗑 Delete account
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
