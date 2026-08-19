import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { playClick } from '../sound.js';

const TX_STATUS = {
  pending: { label: '⏳ Pending', cls: 'pending' },
  approved: { label: '✅ Approved', cls: 'approved' },
  rejected: { label: '❌ Rejected', cls: 'rejected' },
};

export default function SuperAdminPanel({ onError }) {
  const [tab, setTab] = useState('overview');
  const [users, setUsers] = useState([]);
  const [txs, setTxs] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [appeals, setAppeals] = useState([]);
  const [flash, setFlash] = useState('');

  // user detail modal (click a row) — credit editing
  const [selected, setSelected] = useState(null);
  const [editAmt, setEditAmt] = useState('');
  const [detailMsg, setDetailMsg] = useState('');

  // account management
  const [confirmDelAcc, setConfirmDelAcc] = useState(null);
  const [reassignAcc, setReassignAcc] = useState(null); // account id being re-owned
  const [reassignTo, setReassignTo] = useState('');

  // appeal resolution
  const [resDraft, setResDraft] = useState({}); // appeal id -> resolution text

  const flashMsg = (m) => { setFlash(m); setTimeout(() => setFlash(''), 3500); };

  const loadUsers = useCallback(async () => {
    try { setUsers((await api.superAdmin.users()).users || []); }
    catch (e) { onError?.(e.message); }
  }, [onError]);

  const loadTxs = useCallback(async () => {
    try { setTxs((await api.superAdmin.transactions()).transactions || []); }
    catch (e) { onError?.(e.message); }
  }, [onError]);

  const loadAccounts = useCallback(async () => {
    try { setAccounts((await api.superAdmin.accounts()).accounts || []); }
    catch (e) { onError?.(e.message); }
  }, [onError]);

  const loadAppeals = useCallback(async () => {
    try { setAppeals((await api.superAdmin.appeals()).appeals || []); }
    catch (e) { onError?.(e.message); }
  }, [onError]);

  const loadAll = useCallback(async () => {
    await Promise.all([loadUsers(), loadTxs(), loadAccounts(), loadAppeals()]);
  }, [loadUsers, loadTxs, loadAccounts, loadAppeals]);

  // game state for controls
  const [gamePhase, setGamePhase] = useState('preparation');
  const [gamePaused, setGamePaused] = useState(false);
  const [room, setRoom] = useState(10);

  const loadGameState = useCallback(async () => {
    try {
      const d = await api.gameState(room);
      setGamePhase(d.phase || 'preparation');
      setGamePaused(!!d.paused);
    } catch (e) { /* silent */ }
  }, [room]);

  useEffect(() => { loadGameState(); const i = setInterval(loadGameState, 3000); return () => clearInterval(i); }, [loadGameState]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const gameControl = async (fn, okMsg) => {
    playClick();
    try {
      await fn(room);
      flashMsg(okMsg);
      await loadGameState();
    } catch (e) { flashMsg(`❌ ${e.message}`); }
  };

  const adjustCredit = async (delta) => {
    if (!selected) return;
    playClick();
    try {
      const r = await api.superAdmin.credit(selected.user_id, delta, 'user');
      await loadUsers();
      setSelected((s) => (s ? { ...s, ...r } : s));
      setDetailMsg(`✅ ${delta > 0 ? '+' : ''}${delta} credit · now ${r.credit}`);
      setTimeout(() => setDetailMsg(''), 3000);
      setEditAmt('');
    } catch (err) {
      setDetailMsg(`❌ ${err.message}`);
    }
  };

  const toggleAdminRole = async (u, makeAdmin) => {
    playClick();
    try {
      await api.superAdmin.setAdmin(u.user_id, makeAdmin);
      await loadUsers();
      setSelected((s) => (s ? { ...s, is_admin: makeAdmin } : s));
      setDetailMsg(makeAdmin
        ? `✅ ${u.full_name || u.username || u.user_id} is now an admin.`
        : `✅ ${u.full_name || u.username || u.user_id} is no longer an admin.`);
      setTimeout(() => setDetailMsg(''), 3000);
    } catch (err) {
      setDetailMsg(`❌ ${err.message}`);
    }
  };

  const reviewTx = async (id, action) => {
    playClick();
    try {
      await api.superAdmin.reviewTransaction(id, action);
      await loadTxs(); await loadUsers();
      flashMsg(action === 'approve' ? '✅ Transaction approved.' : '❌ Transaction rejected.');
    } catch (err) {
      onError?.(err.message);
    }
  };

  const toggleAccount = async (a) => {
    playClick();
    try {
      await api.superAdmin.updateAccount({ id: a.id, is_active: !a.is_active });
      await loadAccounts();
    } catch (err) { onError?.(err.message); }
  };

  const saveReassign = async (a) => {
    playClick();
    try {
      await api.superAdmin.updateAccount({ id: a.id, admin_id: Number(reassignTo) });
      setReassignAcc(null); setReassignTo('');
      await loadAccounts();
      flashMsg('✅ Account owner changed.');
    } catch (err) { onError?.(err.message); }
  };

  const deleteAccount = async (id) => {
    playClick();
    setConfirmDelAcc(null);
    try {
      await api.superAdmin.deleteAccount(id);
      await loadAccounts();
    } catch (err) { onError?.(err.message); }
  };

  const resolveAppeal = async (a, action) => {
    playClick();
    const resolution = (resDraft[a.id] || '').trim();
    if (action === 'reject' && !resolution) {
      onError?.('Please write a short note explaining the rejection.');
      return;
    }
    try {
      await api.superAdmin.resolveAppeal(a.id, action, resolution);
      await loadAppeals(); await loadTxs(); await loadUsers();
      flashMsg(action === 'approve' ? '✅ Appeal approved — deposit credited.' : '❌ Appeal rejected.');
    } catch (err) {
      onError?.(err.message);
    }
  };

  const pendingTxs = txs.filter((t) => t.status === 'pending').length;
  const pendingAppeals = appeals.filter((a) => a.status === 'pending').length;
  const admins = users.filter((u) => u.is_admin);

  return (
    <div className="panel admin-panel">
      <div className="picker-title">👑 Super Admin controls</div>

      <div className="settings-tabs">
        {[
          ['overview', '📊 Overview'],
          ['users', '👥 All accounts'],
          ['transactions', '🧾 All logs'],
          ['accounts', '💳 Accounts'],
          ['appeals', `⚖️ Appeals${pendingAppeals ? ` (${pendingAppeals})` : ''}`],
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

      {/* -------------------------------------------------------- OVERVIEW */}
      {tab === 'overview' && (
        <div className="admin-stats">
          <div>Accounts (users+admins): <b>{users.length}</b></div>
          <div>Admins: <b>{admins.length}</b></div>
          <div>Pending wallet requests: <b>{pendingTxs}</b></div>
          <div>Pending appeals: <b>{pendingAppeals}</b></div>
          <div>Payment accounts: <b>{accounts.length}</b></div>

          {/* ---- GAME CONTROLS ---- */}
          <div style={{ marginTop: 16 }}>
            <div className="wallet-form-title">🎮 Game Controls</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
              <select
                value={room}
                onChange={(e) => setRoom(Number(e.target.value))}
                style={{ padding: '6px 10px', borderRadius: 8, background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)' }}
              >
                {[10, 20, 30].map((r) => <option key={r} value={r}>Room {r}</option>)}
              </select>
              <span className="user-badge" style={{ alignSelf: 'center' }}>
                {gamePhase} {gamePaused ? '⏸ paused' : ''}
              </span>
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
              {gamePhase === 'preparation' && (
                <button className="btn btn-ghost user-btn" onClick={() => gameControl(api.superAdmin.startGame, '▶️ Round started!')}>▶️ Start</button>
              )}
              {gamePhase === 'playing' && !gamePaused && (
                <button className="btn btn-ghost user-btn" onClick={() => gameControl(api.superAdmin.pauseGame, '⏸️ Game paused.')}>⏸️ Pause</button>
              )}
              {gamePhase === 'playing' && gamePaused && (
                <button className="btn btn-ghost user-btn" onClick={() => gameControl(api.superAdmin.resumeGame, '▶️ Game resumed.')}>▶️ Resume</button>
              )}
              {gamePhase === 'playing' && (
                <button className="btn btn-ghost user-btn danger" onClick={() => gameControl(api.superAdmin.stopGame, '⏹️ Round stopped.')}>⏹️ Stop</button>
              )}
              <button className="btn btn-ghost user-btn" onClick={() => gameControl(api.superAdmin.addBots, '🤖 Bots added!')}>🤖 Add Bots</button>
            </div>
            <p className="reg-hint" style={{ marginTop: 8 }}>
              You control every account, every transaction log, wallet appeals,
              and the game itself.
            </p>
          </div>
        </div>
      )}

      {/* ------------------------------------------------- ALL ACCOUNTS */}
      {tab === 'users' && (
        <div className="users-tab">
          <p className="reg-hint">              Every account — admins AND users. Tap a row to change their{' '}
            <b>credit</b>.
          </p>
          <div className="user-list">
            {users.map((u) => (
              <button
                key={u.user_id}
                className={`user-row clickable ${u.is_registered ? '' : 'unreg'}`}
                onClick={() => { playClick(); setSelected(u); setEditAmt(''); setDetailMsg(''); }}
              >
                <div className="user-info">
                  <div className="user-name">
                    {u.full_name || u.username || `User #${u.user_id}`}
                    {u.is_admin && <span className="user-badge on">admin</span>}
                    {u.online && u.is_admin ? <span className="user-badge on">online</span>
                      : u.is_admin ? <span className="user-badge">offline</span> : null}
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
            {users.length === 0 && <div className="muted">No accounts yet.</div>}
          </div>
        </div>
      )}

      {/* ------------------------------------------------------ ALL LOGS */}
      {tab === 'transactions' && (
        <div className="tx-admin">
          {pendingTxs > 0 && (
            <div className="admin-flash" style={{ color: 'var(--gold)' }}>
              🔔 {pendingTxs} pending request(s)
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
                    {t.provider ? ` · ${t.provider}${t.account_holder ? ` / ${t.account_holder}` : ''} ${t.account_number ? `(${t.account_number})` : ''}` : ''}
                    {t.tx_id ? ` · Ref ${t.tx_id}` : ''} · {t.created_at?.slice(0, 16)}
                    {t.status !== 'pending' ? ` · reviewed ${t.reviewed_at?.slice(0, 16)}` : ''}
                  </span>
                </div>
                <div className="tx-actions">
                  <span className="tx-status">{st.label}</span>
                  {t.status === 'pending' && (
                    <>
                      <button className="btn btn-ghost user-btn" onClick={() => reviewTx(t.id, 'approve')}>✓ Approve</button>
                      <button className="btn btn-ghost user-btn danger" onClick={() => reviewTx(t.id, 'reject')}>✕ Reject</button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* -------------------------------------------------------- ACCOUNTS */}
      {tab === 'accounts' && (
        <div className="account-tab">
          <p className="reg-hint">
            Every admin's payment account. Only the account of an{' '}
            <b>online</b> admin with the most credit is shown to users for each
            bank. You can reassign the owner, toggle it and delete it.
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
                  <div className="user-meta">
                    {a.account_number} · owner{' '}
                    <b>{a.admin_name || `#${a.admin_id || '?'}`}</b>
                    {a.admin_online ? ' 🟢 online' : ' ⚪ offline'}
                  </div>
                </div>
                <div className="user-credit">
                  {reassignAcc === a.id ? (
                    <span className="del-confirm" style={{ display: 'inline-flex' }}>
                      <select value={reassignTo} onChange={(e) => setReassignTo(e.target.value)}>
                        <option value="">owner…</option>
                        {admins.map((ad) => (
                          <option key={ad.user_id} value={ad.user_id}>
                            {ad.full_name || ad.username || ad.user_id}
                          </option>
                        ))}
                      </select>
                      <button className="btn btn-ghost user-btn" disabled={!reassignTo} onClick={() => saveReassign(a)}>OK</button>
                      <button className="btn btn-ghost user-btn" onClick={() => { playClick(); setReassignAcc(null); }}>✕</button>
                    </span>
                  ) : (
                    <button className="btn btn-ghost user-btn" onClick={() => { playClick(); setReassignAcc(a.id); setReassignTo(a.admin_id || ''); }}>
                      👤 Owner
                    </button>
                  )}
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
                    <span className="muted">Delete this account? Past transactions keep their snapshot.</span>
                    <button className="btn btn-danger user-btn" onClick={() => deleteAccount(a.id)}>Yes, delete</button>
                    <button className="btn btn-ghost user-btn" onClick={() => { playClick(); setConfirmDelAcc(null); }}>Cancel</button>
                  </div>
                )}
              </div>
            ))}
            {accounts.length === 0 && <div className="muted">No payment accounts yet.</div>}
          </div>
        </div>
      )}

      {/* --------------------------------------------------------- APPEALS */}
      {tab === 'appeals' && (
        <div className="tx-admin">
          {appeals.length === 0 && <div className="muted">No appeals yet.</div>}
          {appeals.map((a) => (
            <div key={a.id} className={`tx-row ${a.status === 'pending' ? 'pending' : a.status === 'approved' ? 'approved' : 'rejected'}`}>
              <div className="tx-main">
                <span className="tx-type">⚖️ Appeal</span>
                <span className="tx-amount">{a.tx_amount ?? '?'} ETB</span>
                <span className="tx-meta">
                  <b>{a.user_name || `#${a.user_id}`}</b>
                  {a.user_phone ? ` · ${a.user_phone}` : ''}
                  {a.tx_provider ? ` · ${a.tx_provider}` : ''}
                  {a.tx_ref ? ` · Ref ${a.tx_ref}` : ''} · tx {a.tx_status} · {a.created_at?.slice(0, 16)}
                  <br />“{a.reason || 'no reason given'}”
                  {a.resolution && <><br />📝 {a.resolution}</>}
                </span>
              </div>
              <div className="tx-actions">
                <span className="tx-status">
                  {a.status === 'pending' ? '⏳ Pending' : a.status === 'approved' ? '✅ Approved' : '❌ Rejected'}
                </span>
                {a.status === 'pending' && (
                  <>
                    <input
                      className="appeal-res-input"
                      type="text" maxLength={200}
                      placeholder="resolution note…"
                      value={resDraft[a.id] || ''}
                      onChange={(e) => setResDraft((d) => ({ ...d, [a.id]: e.target.value }))}
                    />
                    <button className="btn btn-ghost user-btn" onClick={() => resolveAppeal(a, 'approve')}>✓ Approve</button>
                    <button className="btn btn-ghost user-btn danger" onClick={() => resolveAppeal(a, 'reject')}>✕ Reject</button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ------------------------------------------- USER DETAIL MODAL */}
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
              <div className="profile-row"><span className="muted">Role</span><b>{selected.is_admin ? '🛠 Admin' : '👤 User'}</b></div>
              <div className="profile-row"><span className="muted">Online</span><b>{selected.online ? '🟢 Online' : '⚪ Offline'}</b></div>
              <div className="profile-row"><span className="muted">Rounds played</span><b>{selected.rounds ?? 0}</b></div>
              <div className="profile-row"><span className="muted">Wins</span><b>{selected.wins ?? 0}</b></div>
              <div className="profile-row"><span className="muted">Total winnings</span><b className="gold">{selected.total_winnings ?? 0} ETB</b></div>
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
                Changes the player wallet balance.
              </p>
            </div>

            <div className="credit-edit">
              <div className="wallet-form-title">
                🛠 Role: <b>{selected.is_admin ? 'Admin' : 'User'}</b>
                {selected.env_admin && <span className="muted"> · core admin (from .env)</span>}
              </div>
              {!selected.env_admin && (
                <div className="wallet-form-row">
                  {selected.is_admin ? (
                    <button className="btn btn-ghost user-btn" onClick={() => toggleAdminRole(selected, false)}>
                      Demote to user
                    </button>
                  ) : (
                    <button className="btn btn-ghost user-btn" onClick={() => toggleAdminRole(selected, true)}>
                      🛠 Make admin
                    </button>
                  )}
                </div>
              )}
              <p className="reg-hint">
                Admins get the 🛠 Admin panel, can post their own payment
                accounts and approve wallet requests.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
