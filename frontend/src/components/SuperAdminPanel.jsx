import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { playClick } from '../sound.js';
import { getTelegramUser } from '../telegram.js';

const TX_STATUS = {
  pending: { label: '⏳ Pending', cls: 'pending' },
  approved: { label: '✅ Approved', cls: 'approved' },
  rejected: { label: '❌ Rejected', cls: 'rejected' },
};

export default function SuperAdminPanel({ onError, onChanged }) {
  const [tab, setTab] = useState('overview');
  const [users, setUsers] = useState([]);
  const [txs, setTxs] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [appeals, setAppeals] = useState([]);
  const [activities, setActivities] = useState([]);
  const [gameHistory, setGameHistory] = useState([]);
  const [announcements, setAnnouncements] = useState([]);
  const [announceText, setAnnounceText] = useState('');
  const [flash, setFlash] = useState('');

  // user detail modal (click a row) — credit editing
  const [selected, setSelected] = useState(null);
  const [editAmt, setEditAmt] = useState('');
  const [detailMsg, setDetailMsg] = useState('');
  const [editName, setEditName] = useState('');
  const [editPhone, setEditPhone] = useState('');

  // account management
  const [confirmDelAcc, setConfirmDelAcc] = useState(null);
  const [reassignAcc, setReassignAcc] = useState(null);
  const [reassignTo, setReassignTo] = useState('');

  // appeal resolution
  const [resDraft, setResDraft] = useState({});

  // inline delete confirm for users
  const [confirmDel, setConfirmDel] = useState(null);

  // payment account form
  const [accForm, setAccForm] = useState({ provider: '', account_name: '', account_number: '', is_active: true });
  const [editingAcc, setEditingAcc] = useState(null);

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

  const loadActivities = useCallback(async () => {
    try { setActivities((await api.superAdmin.activityLog()).activities || []); }
    catch (e) { onError?.(e.message); }
  }, [onError]);

  const loadGameHistory = useCallback(async () => {
    try { const d = await api.superAdmin.gameplayHistory(); setGameHistory(d?.history || []); }
    catch (e) { /* silent — endpoint may not exist yet */ }
  }, []);

  const loadAnnouncements = useCallback(async () => {
    try { const d = await api.announcements(); setAnnouncements(d?.announcements || []); }
    catch (e) { /* silent — endpoint may not exist yet */ }
  }, []);

  const loadAll = useCallback(async () => {
    await Promise.all([loadUsers(), loadTxs(), loadAccounts(), loadAppeals(), loadActivities(), loadGameHistory(), loadAnnouncements()]);
  }, [loadUsers, loadTxs, loadAccounts, loadAppeals, loadActivities, loadGameHistory, loadAnnouncements]);

  // game state for controls
  const [gamePhase, setGamePhase] = useState('preparation');
  const [gamePaused, setGamePaused] = useState(false);
  const [room, setRoom] = useState(10);
  const [botsEnabled, setBotsEnabled] = useState(true);
  const [botsDifficulty, setBotsDifficulty] = useState(2);
  const [realPlayers, setRealPlayers] = useState(0);
  const [botsPlayers, setBotsPlayers] = useState(0);
  const [cardsInPlay, setCardsInPlay] = useState(0);

  const DIFFICULTY_LABELS = ['Easy', 'Normal', 'Medium', 'Hard', 'Very Hard', 'Impossible'];
  const DIFFICULTY_COLORS = ['#4caf50', '#8bc34a', '#ff9800', '#ff5722', '#e91e63', '#d50000'];

  const loadGameState = useCallback(async () => {
    try {
      const { state: d } = await api.gameState(room);
      setGamePhase(d.phase || 'preparation');
      setGamePaused(!!d.paused);
      setBotsEnabled(!!d.bots_enabled);
      setBotsDifficulty(d.bots_difficulty ?? 2);
      setRealPlayers(d.real_players ?? 0);
      setBotsPlayers(d.bots_players ?? 0);
      setCardsInPlay(d.cards_in_play ?? 0);
    } catch (e) { /* silent */ }
  }, [room]);

  useEffect(() => { loadGameState(); const i = setInterval(loadGameState, 3000); return () => clearInterval(i); }, [loadGameState]);

  useEffect(() => { loadAll(); }, [loadAll]);
  useEffect(() => { const i = setInterval(loadAppeals, 10000); return () => clearInterval(i); }, [loadAppeals]);
  useEffect(() => { const i = setInterval(loadActivities, 15000); return () => clearInterval(i); }, [loadActivities]);
  useEffect(() => { const i = setInterval(loadAnnouncements, 20000); return () => clearInterval(i); }, [loadAnnouncements]);

  const gameControl = async (fn, okMsg) => {
    playClick();
    try {
      await fn(room);
      flashMsg(okMsg);
      await loadGameState();
    } catch (e) { flashMsg(`❌ ${e.message}`); }
  };

  // ---- PAUSE / RESUME ----
  const pauseGame = async () => {
    playClick();
    try {
      await api.superAdmin.pauseGame(room);
      setGamePaused(true);
      flashMsg('⏸️ Game paused for ALL players.');
      await loadGameState();
    } catch (e) {
      flashMsg(e.message?.includes('404') || e.message?.includes('Not Found')
        ? '⏸️ Pause not available yet — backend update needed.'
        : `❌ ${e.message}`);
    }
  };

  const resumeGame = async () => {
    playClick();
    try {
      await api.superAdmin.resumeGame(room);
      setGamePaused(false);
      flashMsg('▶️ Game resumed!');
      await loadGameState();
    } catch (e) {
      flashMsg(e.message?.includes('404') || e.message?.includes('Not Found')
        ? '▶️ Resume not available yet — backend update needed.'
        : `❌ ${e.message}`);
    }
  };

  // ---- ANNOUNCEMENTS ----
  const postAnnouncement = async () => {
    const text = announceText.trim();
    if (!text) { flashMsg('Type an announcement first.'); return; }
    playClick();
    try {
      await api.superAdmin.postAnnouncement(text);
      setAnnounceText('');
      flashMsg('📢 Announcement posted to all users, admins & super admins!');
      await loadAnnouncements();
      onChanged?.();
    } catch (e) {
      flashMsg(e.message?.includes('404') || e.message?.includes('Not Found')
        ? '📢 Announcements not available yet — backend update needed.'
        : `❌ ${e.message}`);
    }
  };

  // ---- CREDIT EDITING ----
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

  // ---- ADMIN ROLE ----
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

  const saveUserEdit = async () => {
    if (!selected) return;
    playClick();
    try {
      const fields = {};
      if (editName.trim()) fields.full_name = editName.trim();
      if (editPhone.trim()) fields.phone = editPhone.trim();
      if (Object.keys(fields).length === 0) {
        setDetailMsg('Nothing to save.');
        return;
      }
      const r = await api.superAdmin.editUser(selected.user_id, fields);
      await loadUsers();
      setSelected((s) => s ? { ...s, full_name: r.full_name, phone: r.phone } : s);
      setDetailMsg('✅ Account details updated.');
      setTimeout(() => setDetailMsg(''), 3000);
    } catch (err) {
      setDetailMsg(`❌ ${err.message}`);
    }
  };

  const deleteUser = async (target) => {
    playClick();
    setConfirmDel(null);
    try {
      // Use the admin-level delete which also works for super admin
      const user = getTelegramUser();
      await fetch('/api/admin/users/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: target, admin_id: user.id }),
      }).then(r => r.json()).then(d => { if (d.error) throw new Error(d.error); });
      if (selected?.user_id === target) setSelected(null);
      await loadUsers();
      onChanged?.();
      flashMsg('✅ User deleted.');
    } catch (err) {
      flashMsg(`❌ ${err.message}`);
    }
  };

  // ---- TRANSACTIONS ----
  const reviewTx = async (id, action) => {
    playClick();
    try {
      await api.superAdmin.reviewTransaction(id, action);
      await loadTxs(); await loadUsers();
      flashMsg(action === 'approve' ? '✅ Transaction approved.' : '❌ Transaction rejected.');
      onChanged?.();
    } catch (err) {
      onError?.(err.message);
    }
  };

  // ---- PAYMENT ACCOUNTS ----
  const saveAccount = async (e) => {
    e.preventDefault();
    playClick();
    try {
      if (editingAcc) {
        await api.superAdmin.updateAccount({ id: editingAcc, ...accForm });
      } else {
        // Use admin-level add which also works for super admin
        const user = getTelegramUser();
        await fetch('/api/admin/accounts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...accForm, admin_id: user.id }),
        }).then(r => r.json()).then(d => { if (d.error) throw new Error(d.error); });
      }
      setAccForm({ provider: '', account_name: '', account_number: '', is_active: true });
      setEditingAcc(null);
      flashMsg('✅ Payment account saved.');
      setTimeout(() => setFlash(''), 3000);
      await loadAccounts();
      onChanged?.();
    } catch (err) {
      flashMsg(`❌ ${err.message}`);
    }
  };

  const toggleAccount = async (a) => {
    playClick();
    try {
      await api.superAdmin.updateAccount({ id: a.id, is_active: !a.is_active });
      await loadAccounts();
    } catch (err) { onError?.(err.message); }
  };

  const editAccount = (a) => {
    playClick();
    setEditingAcc(a.id);
    setAccForm({ provider: a.provider, account_name: a.account_name, account_number: a.account_number, is_active: a.is_active });
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

  // ---- APPEALS ----
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
      onChanged?.();
    } catch (err) {
      onError?.(err.message);
    }
  };

  const pendingTxs = txs.filter((t) => t.status === 'pending').length;
  const pendingAppeals = appeals.filter((a) => a.status === 'pending').length;
  const admins = users.filter((u) => u.is_admin);

  const tabs = [
    ['overview', '📊 Overview'],
    ['users', '👥 All Users'],
    ['transactions', '🧾 All Logs'],
    ['accounts', '💳 Accounts'],
    ['appeals', `⚖️ Appeals${pendingAppeals ? ` (${pendingAppeals})` : ''}`],
    ['activity', '📋 Activity Log'],
    ['history', '🎮 Game History'],
    ['announce', '📢 Announcements'],
  ];

  return (
    <div className="panel admin-panel">
      <div className="picker-title">👑 Super Admin controls</div>

      <div className="settings-tabs">
        {tabs.map(([id, label]) => (
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
                {gamePaused ? '⏸️ PAUSED' : gamePhase}
              </span>
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8, fontSize: 12, fontWeight: 700 }}>
              <span style={{ color: 'var(--green)' }}>👤 Humans: <b>{realPlayers}</b></span>
              <span style={{ color: 'var(--muted)' }}>🤖 Bots: <b>{botsPlayers}</b></span>
              <span style={{ color: 'var(--gold)' }}>🃏 Cards: <b>{cardsInPlay}</b></span>
              <span style={{ color: 'var(--purple)' }}>👥 Total: <b>{realPlayers + botsPlayers}</b></span>
            </div>

            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
              {gamePhase === 'preparation' && !gamePaused && (
                <button className="btn btn-ghost user-btn" onClick={() => gameControl(api.superAdmin.startGame, '▶️ Round started!')}>▶️ Start</button>
              )}

              {gamePhase === 'playing' && (
                <button className="btn btn-ghost user-btn danger" onClick={() => gameControl(api.superAdmin.stopGame, '⏹️ Round stopped.')}>⏹️ Stop</button>
              )}

              {/* ---- PAUSE / RESUME (super admin only) ---- */}
              {!gamePaused && gamePhase !== 'ended' && (
                <button
                  className="btn btn-ghost user-btn"
                  style={{ background: 'rgba(255, 165, 0, 0.15)', color: '#ffa500', border: '1px solid rgba(255, 165, 0, 0.4)' }}
                  onClick={pauseGame}
                >
                  ⏸️ Pause Game
                </button>
              )}
              {gamePaused && (
                <button
                  className="btn btn-ghost user-btn"
                  style={{ background: 'rgba(75, 227, 160, 0.15)', color: 'var(--green)', border: '1px solid rgba(75, 227, 160, 0.4)' }}
                  onClick={resumeGame}
                >
                  ▶️ Resume Game
                </button>
              )}

              <button
                className="btn btn-ghost user-btn"
                style={botsEnabled ? { opacity: 1, color: 'var(--gold)' } : { opacity: 0.5 }}
                onClick={async () => {
                  playClick();
                  const newEnabled = !botsEnabled;
                  try {
                    await api.superAdmin.toggleBots(newEnabled);
                    setBotsEnabled(newEnabled);
                    flashMsg(newEnabled ? '🤖 Bots enabled.' : '🤖 Bots disabled.');
                  } catch (e) { flashMsg(`❌ ${e.message}`); }
                }}
              >
                {botsEnabled ? '🟢 Disable Bots' : '🔴 Enable Bots'}
              </button>
            </div>

            {/* ---- BOT DIFFICULTY SLIDER ---- */}
            <div style={{ marginTop: 10, padding: '8px 10px', borderRadius: 8, background: 'var(--bg)', border: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)' }}>🤖 Bot Difficulty</span>
                <span style={{ fontSize: 12, fontWeight: 800, color: DIFFICULTY_COLORS[botsDifficulty] }}>
                  {DIFFICULTY_LABELS[botsDifficulty]}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 4 }}>
                {DIFFICULTY_LABELS.map((label, i) => (
                  <button
                    key={i}
                    onClick={async () => {
                      playClick();
                      try {
                        await api.superAdmin.setBotsDifficulty(i);
                        setBotsDifficulty(i);
                        flashMsg(`🤖 Bot difficulty: ${label}`);
                      } catch (e) { flashMsg(`❌ ${e.message}`); }
                    }}
                    style={{
                      flex: 1, padding: '6px 2px', borderRadius: 6, border: 'none',
                      fontSize: 10, fontWeight: botsDifficulty === i ? 800 : 600,
                      cursor: 'pointer', transition: 'all 0.2s',
                      background: botsDifficulty === i ? DIFFICULTY_COLORS[i] : 'var(--surface)',
                      color: botsDifficulty === i ? '#fff' : 'var(--muted)',
                      boxShadow: botsDifficulty === i ? `0 2px 8px ${DIFFICULTY_COLORS[i]}44` : 'none',
                    }}
                    title={label}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className="reg-hint" style={{ marginTop: 4, marginBottom: 0 }}>
                {botsDifficulty === 0 && '🟢 Powerless — bots almost never win'}
                {botsDifficulty === 1 && '🟢 Slow claim — bots rarely beat humans'}
                {botsDifficulty === 2 && '🟡 Default — balanced difficulty'}
                {botsDifficulty === 3 && '🟠 Fast claim — bots often win'}
                {botsDifficulty === 4 && '🔴 Near-instant — very powerful bots'}
                {botsDifficulty === 5 && '🔴 Instant claim — impossible to beat!'}
              </p>
            </div>
            <p className="reg-hint" style={{ marginTop: 8 }}>
              You control every account, every transaction log, wallet appeals,
              and the game itself. Only you can pause and resume the game.
            </p>
          </div>
        </div>
      )}

      {/* ------------------------------------------------- ALL USERS */}
      {tab === 'users' && (
        <div className="users-tab">
          <p className="reg-hint">
            Every account — admins AND users. Tap a row to change their <b>credit</b>.
          </p>
          <div className="user-list">
            {users.map((u) => (
              <button
                key={u.user_id}
                className={`user-row clickable ${u.is_registered ? '' : 'unreg'}`}
                onClick={() => { playClick(); setSelected(u); setEditAmt(''); setEditName(''); setEditPhone(''); setDetailMsg(''); }}
              >
                <div className="user-info">
                  <div className="user-name">
                    {u.full_name || u.username || `User #${u.user_id}`}
                    {u.is_admin && <span className="user-badge on">admin</span>}
                    {u.is_super_admin && <span className="user-badge" style={{ background: 'rgba(217,92,255,0.18)', color: 'var(--purple)', borderColor: 'rgba(217,92,255,0.4)' }}>super</span>}
                    {u.online && (u.is_admin || u.is_super_admin) ? <span className="user-badge on">online</span>
                      : (u.is_admin || u.is_super_admin) ? <span className="user-badge">offline</span> : null}
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
            Every admin's payment account. <b>Super admin accounts are always shown to users for deposits, even when offline.</b> You can reassign the owner, toggle it and delete it.
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
                    {a.is_super_admin_account && (
                      <span className="user-badge" style={{ background: 'rgba(217,92,255,0.18)', color: 'var(--purple)', borderColor: 'rgba(217,92,255,0.4)' }}>
                        👑 always visible
                      </span>
                    )}
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
                  <br />"{a.reason || 'no reason given'}"
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

      {/* -------------------------------------------------- ACTIVITY LOG */}
      {tab === 'activity' && (
        <div className="tx-admin">
          <p className="reg-hint">All critical activities are logged here — new players, deposits, withdrawals, credit adjustments, appeals, and game controls.</p>
          <div style={{ marginTop: 8 }}>
            <button className="btn btn-ghost user-btn" onClick={() => { playClick(); loadActivities(); }}>
              🔄 Refresh
            </button>
          </div>
          {activities.length === 0 && <div className="muted" style={{ marginTop: 12 }}>No activities logged yet.</div>}
          {activities.map((a) => (
            <div key={a.id} className="tx-row" style={{ fontSize: 11 }}>
              <div className="tx-main" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
                <span style={{ fontWeight: 800, color: 'var(--gold)' }}>{a.action.replace(/_/g, ' ').toUpperCase()}</span>
                <span className="tx-meta">
                  {a.user_name ? <b>{a.user_name}</b> : a.user_id ? `User #${a.user_id}` : 'System'}
                  {a.details ? ` · ${a.details}` : ''}
                  {a.created_at ? ` · ${a.created_at.slice(0, 16)}` : ''}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ------------------------------------------------- GAME HISTORY */}
      {tab === 'history' && (
        <div className="tx-admin">
          <p className="reg-hint">
            🎮 Gameplay history — only rounds with <b>at least one human player</b> are recorded here. Each entry shows the round result, winner, players, and prize pool.
          </p>
          <div style={{ marginTop: 8 }}>
            <button className="btn btn-ghost user-btn" onClick={() => { playClick(); loadGameHistory(); }}>
              🔄 Refresh
            </button>
          </div>
          {gameHistory.length === 0 && <div className="muted" style={{ marginTop: 12 }}>No gameplay history yet — games with human players will appear here.</div>}
          {gameHistory.map((g, i) => (
            <div key={g.id || i} className={`tx-row ${g.winner_id ? 'approved' : ''}`} style={{ fontSize: 11 }}>
              <div className="tx-main" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
                <span style={{ fontWeight: 800, color: g.winner_id ? 'var(--gold)' : 'var(--muted)' }}>
                  🎮 Room {g.room ?? '?'} · {g.pattern || 'No winner'}
                </span>
                <span className="tx-meta">
                  {g.winner_name ? <>🏆 <b>{g.winner_name}</b> won <b className="gold">{g.prize} ETB</b></> : 'No winner this round'}
                  {g.human_players != null ? ` · ${g.human_players} human player(s)` : ''}
                  {g.total_players != null ? ` · ${g.total_players} total` : ''}
                  {g.cards_played != null ? ` · ${g.cards_played} cards` : ''}
                  {g.called_count != null ? ` · ${g.called_count}/75 balls` : ''}
                  {g.created_at ? ` · ${g.created_at.slice(0, 16)}` : ''}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ------------------------------------------------ ANNOUNCEMENTS */}
      {tab === 'announce' && (
        <div className="tx-admin">
          <p className="reg-hint">
            📢 Post announcements that are visible to <b>all users, admins, and super admins</b>. Use this for important updates, maintenance notices, or promotions.
          </p>

          <div className="credit-edit" style={{ marginTop: 12 }}>
            <div className="wallet-form-title">📢 New Announcement</div>
            <div className="wallet-form-row" style={{ flexDirection: 'column', gap: 8 }}>
              <textarea
                rows={3}
                maxLength={500}
                placeholder="Type your announcement… (visible to everyone)"
                value={announceText}
                onChange={(e) => setAnnounceText(e.target.value)}
                style={{
                  width: '100%', padding: '10px', borderRadius: 10,
                  background: 'rgba(0,0,0,0.35)', border: '1px solid var(--border)',
                  color: 'var(--text)', fontSize: 13, fontFamily: 'inherit', resize: 'vertical',
                }}
              />
              <button
                className="btn btn-primary"
                disabled={!announceText.trim()}
                onClick={postAnnouncement}
                style={{ alignSelf: 'flex-start' }}
              >
                📢 Post Announcement
              </button>
            </div>
          </div>

          {announcements.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div className="wallet-form-title">📋 Recent Announcements</div>
              {announcements.map((a) => (
                <div key={a.id} className="tx-row approved" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 4 }}>
                  <div style={{ fontWeight: 800, color: 'var(--gold)', fontSize: 12 }}>📢 Announcement</div>
                  <div style={{ fontSize: 13, color: 'var(--text)' }}>{a.text}</div>
                  <div className="tx-meta">
                    {a.posted_by ? <b>{a.posted_by}</b> : 'System'} · {a.created_at?.slice(0, 16)}
                  </div>
                </div>
              ))}
            </div>
          )}
          {announcements.length === 0 && (
            <div className="muted" style={{ marginTop: 12 }}>No announcements yet.</div>
          )}
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
              <div className="profile-row"><span className="muted">Role</span><b>{selected.is_super_admin ? '👑 Super Admin' : selected.is_admin ? '🛠 Admin' : '👤 User'}</b></div>
              <div className="profile-row"><span className="muted">Online</span><b>{selected.online ? '🟢 Online' : '⚪ Offline'}</b></div>
              <div className="profile-row"><span className="muted">Rounds played</span><b>{selected.rounds ?? 0}</b></div>
              <div className="profile-row"><span className="muted">Wins</span><b>{selected.wins ?? 0}</b></div>
              <div className="profile-row"><span className="muted">Total winnings</span><b className="gold">{selected.total_winnings ?? 0} ETB</b></div>
              <div className="profile-row"><span className="muted">Referrals</span><b>{selected.referral_count ?? 0} users</b></div>
              <div className="profile-row"><span className="muted">Referral earnings</span><b className="gold">{selected.referral_commission ?? 0} ETB</b></div>
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
                🛠 Role: <b>{selected.is_super_admin ? '👑 Super Admin' : selected.is_admin ? 'Admin' : 'User'}</b>
                {selected.env_admin && <span className="muted"> · core admin (from .env)</span>}
              </div>
              {!selected.env_admin && !selected.is_super_admin && (
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

            {/* ---- EDIT ACCOUNT DETAILS (super admin only) ---- */}
            <div className="credit-edit">
              <div className="wallet-form-title">
                ✏️ Edit Account Details
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="muted" style={{ minWidth: 80, fontSize: 12 }}>Full name</span>
                  <input
                    type="text"
                    placeholder={selected.full_name || 'No name'}
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    style={{ flex: 1, padding: '6px 10px', borderRadius: 8, background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', fontSize: 13 }}
                  />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="muted" style={{ minWidth: 80, fontSize: 12 }}>Phone</span>
                  <input
                    type="text"
                    placeholder={selected.phone || 'No phone'}
                    value={editPhone}
                    onChange={(e) => setEditPhone(e.target.value)}
                    style={{ flex: 1, padding: '6px 10px', borderRadius: 8, background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', fontSize: 13 }}
                  />
                </div>
                <button
                  className="btn btn-ghost user-btn"
                  onClick={saveUserEdit}
                  disabled={!editName.trim() && !editPhone.trim()}
                  style={{ alignSelf: 'flex-start', marginTop: 4 }}
                >
                  💾 Save Changes
                </button>
              </div>
              <p className="reg-hint">
                Edit any user's name and phone number.
              </p>
            </div>

            {/* ---- DANGER ZONE: DELETE USER ---- */}
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

