import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { playClick, PACKS, getPack, setPack } from '../sound.js';
import { PATTERN_LABELS } from '../bingo.js';
import ReferralPanel from './ReferralPanel.jsx';

const TX_STATUS = {
  pending: { label: '⏳ Pending', cls: 'pending' },
  approved: { label: '✅ Approved', cls: 'approved' },
  rejected: { label: '❌ Rejected', cls: 'rejected' },
};

// Icon lookup for known providers (used for display only)
const PROVIDER_ICONS = {
  'telebirr': '📱',
  'cbe birr': '🏦', 'cbe': '🏦', 'cbb': '🏦',
  'awash bank': '🏦', 'dashen bank': '🏦', 'wegagen bank': '🏦',
  'united bank': '🏦', 'abyssinia bank': '🏦', 'nib international bank': '🏦',
  'berhan bank': '🏦', 'bunna bank': '🏦', 'abay bank': '🏦',
  'cooperative bank': '🏦', 'hijra bank': '🏦', 'zemen bank': '🏦',
  'lion international bank': '🏦', 'oromia international bank': '🏦',
  'global bank': '🏦', 'enat bank': '🏦', 'ahadu bank': '🏦',
  'gadahad bank': '🏦', 'meb bank': '🏦', 'samuel bank': '🏦',
  'tsedey bank': '🏦', 'amhara bank': '🏦', 'zamzam bank': '🏦',
};

function getProviderIcon(name) {
  return PROVIDER_ICONS[(name || '').toLowerCase()] || '🏦';
}

const WINNING_PATTERNS = [
  { key: 'Row', desc: 'All 5 numbers in any horizontal row.' },
  { key: 'Column', desc: 'All 5 numbers in any vertical column.' },
  { key: 'Diagonal', desc: 'Both long diagonals (top-left → bottom-right).' },
  { key: 'Anti-Diagonal', desc: 'The other diagonal (top-right → bottom-left).' },
  { key: 'Four Corners', desc: 'The 4 corner numbers — the centre FREE cell does not count.' },
];

export default function Settings({ user, settings, config, onChanged, onError, onClose }) {
  const [tab, setTab] = useState('wallet');
  const [txs, setTxs] = useState([]);
  // the deposit picker works per BANK: the system shows ONE account per bank
  // (the online admin with the most credit) — the user picks the bank, not
  // the account
  const [depProvider, setDepProvider] = useState('');
  const [depAmount, setDepAmount] = useState('');
  const [depTx, setDepTx] = useState('');
  const [wdAmount, setWdAmount] = useState('');
  // withdraw destination account details (required): account name (provider),
  // holder's name and the account number the money should be sent to
  const [wdAccount, setWdAccount] = useState('');
  const [wdHolder, setWdHolder] = useState('');
  const [wdNumber, setWdNumber] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState('');
  const [copied, setCopied] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [nameDraft, setNameDraft] = useState(user?.full_name || '');
  const [phoneDraft, setPhoneDraft] = useState(user?.phone || '');
  const [soundPack, setSoundPack] = useState(() => getPack());

  // wallet appeals: a deposit the admin never approved can be appealed to the
  // SUPER ADMIN
  const [appeals, setAppeals] = useState([]);
  const [appealTx, setAppealTx] = useState(null);
  const [appealReason, setAppealReason] = useState('');

  // announcements: essential messages from the super admin
  const [announcements, setAnnouncements] = useState([]);

  // deposit_accounts = ONE account per bank/provider — always the account of
  // the ONLINE admin with the most credit; offline admins' accounts are never
  // listed. BUT: super admin accounts are ALWAYS shown even when offline.
  const depositAccounts = settings?.deposit_accounts || [];
  // Build a lookup of admin accounts by provider name (case-insensitive)
  const onlineAccountsMap = {};
  depositAccounts.forEach((d) => {
    const key = d.provider.toLowerCase();
    // Super admin accounts always take priority — they're shown even when offline
    if (d.is_super_admin_account) {
      onlineAccountsMap[key] = d;
    } else if (!onlineAccountsMap[key]) {
      onlineAccountsMap[key] = d;
    }
  });
  // Available banks: only those that have at least one active admin account
  // (either an online admin or super admin fallback). The providers list comes
  // from the server — only banks with accounts are included.
  const availableProviders = settings?.providers || [];
  const availableBanks = availableProviders.map((name) => ({
    name,
    icon: getProviderIcon(name),
    hasOnline: !!onlineAccountsMap[name.toLowerCase()],
  }));
  const banksWithOnlineAdmin = availableBanks.filter((b) => b.hasOnline);
  const banksWithoutOnlineAdmin = availableBanks.filter((b) => !b.hasOnline);
  // Selected bank's online admin account
  const selectedBankInfo = availableBanks.find((b) => b.name === depProvider);
  const selectedDep = selectedBankInfo ? (onlineAccountsMap[depProvider.toLowerCase()] || null) : null;
  const accId = selectedDep ? selectedDep.account.id : null;

  // Withdraw bank selection: show the same banks so the user can pick which
  // bank they want their withdrawal sent through, and display the admin
  // account info for that bank.
  const selectedWdBank = availableBanks.find((b) => b.name === wdAccount);
  const selectedWdDep = selectedWdBank ? (onlineAccountsMap[wdAccount.toLowerCase()] || null) : null;

  const loadTxs = useCallback(async () => {
    try {
      const d = await api.transactions();
      setTxs(d.transactions || []);
    } catch (e) {
      onError?.(e.message);
    }
  }, [onError]);

  const loadAppeals = useCallback(async () => {
    try {
      const d = await api.appeals();
      setAppeals(d.appeals || []);
    } catch (e) {
      /* appeals are a convenience — never block the wallet on them */
    }
  }, []);

  useEffect(() => { loadTxs(); loadAppeals(); }, [loadTxs, loadAppeals]);

  const loadAnnouncements = useCallback(async () => {
    try {
      const d = await api.announcements();
      setAnnouncements(d?.announcements || []);
    } catch (e) { /* silent — endpoint may not exist yet */ }
  }, []);

  useEffect(() => { loadAnnouncements(); }, [loadAnnouncements]);
  useEffect(() => { const i = setInterval(loadAnnouncements, 15000); return () => clearInterval(i); }, [loadAnnouncements]);

  // default the deposit picker to the first available bank
  useEffect(() => {
    if (!depProvider && availableBanks.length) {
      setDepProvider(availableBanks[0].name);
    }
  }, [availableBanks.length, depProvider]);

  // default the withdraw bank picker to the first available bank
  useEffect(() => {
    if (!wdAccount && availableBanks.length) {
      setWdAccount(availableBanks[0].name);
    }
  }, [availableBanks.length, wdAccount]);

  const flash = (m) => { setMsg(m); setTimeout(() => setMsg(''), 4000); };

  const copyAccount = async (acc) => {
    try {
      await navigator.clipboard.writeText(acc.account_number);
      setCopied(acc.id);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      flash('Could not copy — please copy the number manually.');
    }
  };

  const submitDeposit = async (e) => {
    e.preventDefault();
    if (!accId) {
      flash('❌ Please select the bank/account you sent the money to.');
      return;
    }
    playClick();
    setBusy('dep');
    try {
      await api.createTransaction('deposit', Number(depAmount), depTx.trim(), accId);
      setDepAmount(''); setDepTx('');
      flash('✅ Deposit request sent! The online admin will verify and credit your balance.');
      await loadTxs(); await onChanged();
    } catch (err) {
      flash(`❌ ${err.message}`);
    } finally {
      setBusy('');
    }
  };

  const submitAppeal = async () => {
    playClick();
    setBusy('appeal');
    try {
      await api.fileAppeal(appealTx, appealReason.trim());
      setAppealTx(null); setAppealReason('');
      flash('✅ Appeal submitted! The super admin will review it.');
      await loadAppeals();
    } catch (err) {
      flash(`❌ ${err.message}`);
    } finally {
      setBusy('');
    }
  };

  const submitWithdraw = async (e) => {
    e.preventDefault();
    playClick();
    setBusy('wd');
    try {
      await api.createTransaction('withdraw', Number(wdAmount), '', null, {
        account_name: wdAccount.trim(),
        account_holder: wdHolder.trim(),
        account_number: wdNumber.trim(),
      });
      setWdAmount(''); setWdAccount(''); setWdHolder(''); setWdNumber('');
      flash('✅ Withdrawal request sent! The admin will send the money to the account you provided once approved.');
      await loadTxs(); await onChanged();
    } catch (err) {
      flash(`❌ ${err.message}`);
    } finally {
      setBusy('');
    }
  };

  const saveName = async (e) => {
    e.preventDefault();
    const name = nameDraft.trim();
    if (!name) { flash('❌ Please enter your full name.'); return; }
    playClick();
    setBusy('name');
    try {
      await api.updateProfile({ full_name: name });
      flash('✅ Your name has been updated.');
      await onChanged();
    } catch (err) {
      flash(`❌ ${err.message}`);
    } finally {
      setBusy('');
    }
  };

  const savePhone = async (e) => {
    e.preventDefault();
    const phone = phoneDraft.replace(/\s+/g, '').trim();
    if (!phone) { flash('❌ Please enter your phone number.'); return; }
    playClick();
    setBusy('phone');
    try {
      await api.updateProfile({ phone });
      flash('✅ Your phone (wallet) has been updated.');
      await onChanged();
    } catch (err) {
      flash(`❌ ${err.message}`);
    } finally {
      setBusy('');
    }
  };

  const deleteAccount = async () => {
    playClick();
    try {
      await api.deleteAccount();
      // the account no longer exists -> go back to the registration screen
      onChanged(); // re-fetch (will show registration gate)
    } catch (err) {
      flash(`❌ ${err.message}`);
    }
  };

  const currency = settings?.currency || 'ETB';

  return (
    <div className="panel settings-panel">
      <div className="settings-head">
        <div className="picker-title">⚙️ Settings</div>
        <button className="chip chip-btn" onClick={() => { playClick(); onClose(); }}>✕ Close</button>
      </div>

      <div className="settings-tabs">
        {[
          ['wallet', '💰 Wallet'],
          ['profile', '👤 Profile'],
          ['referral', '🔗 Referral'],
          ['sound', '🔊 Sound'],
          ['help', '❓ Help & Guide'],
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

      {msg && <div className="admin-flash">{msg}</div>}

      {/* ---------------------------------------------------------- WALLET */}
      {tab === 'wallet' && (
        <div className="wallet">

          {/* ---- ANNOUNCEMENTS BANNER ---- */}
          {announcements.length > 0 && (
            <div className="announcements-banner">
              <div className="announcements-header">📢 Announcements</div>
              {announcements.slice(0, 3).map((a) => (
                <div key={a.id} className="announcement-item">
                  <span className="announcement-text">{a.text}</span>
                  <span className="announcement-meta">
                    {a.posted_by ? `— ${a.posted_by}` : ''} {a.created_at?.slice(0, 10)}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="wallet-balance">
            <span className="wallet-balance-label">Your balance</span>
            <span className="wallet-balance-num">
              {user?.credit ?? 0} <small>{currency}</small>
            </span>
          </div>

          <div className="acc-picker">
            <div className="wallet-form-title">💳 Select your bank</div>
            <p className="reg-hint" style={{ marginTop: -4, marginBottom: 8 }}>
              Choose the bank or mobile wallet you want to pay into.
            </p>

            {/* Bank listbox — clean dropdown */}
            <select
              className="room-select"
              style={{ width: '100%', maxWidth: '100%', padding: '10px 12px', fontSize: 14 }}
              value={depProvider}
              onChange={(e) => { playClick(); setDepProvider(e.target.value); }}
            >
              <option value="">— Pick a bank —</option>
              {banksWithOnlineAdmin.length > 0 && (
                <optgroup label="✅ Available now">
                  {banksWithOnlineAdmin.map((b) => (
                    <option key={b.name} value={b.name}>{b.icon} {b.name}</option>
                  ))}
                </optgroup>
              )}
              {banksWithoutOnlineAdmin.length > 0 && (
                <optgroup label="⏳ Unavailable (no admin online)">
                  {banksWithoutOnlineAdmin.map((b) => (
                    <option key={b.name} value={b.name} disabled>{b.icon} {b.name}</option>
                  ))}
                </optgroup>
              )}
            </select>

          {availableBanks.length === 0 && (
            <div className="reg-hint" style={{ color: 'var(--gold)', marginTop: 8 }}>
              ⏳ No bank accounts are available right now. No admin has added a payment account yet.
            </div>
          )}
          </div>

          {/* Show selected bank's admin account as a beautiful inline card */}
          {selectedDep && (
            <div style={{
              background: 'linear-gradient(135deg, rgba(62,200,255,0.08), rgba(255,213,79,0.06))',
              border: '1px solid rgba(62,200,255,0.3)', borderRadius: 14, padding: 14, marginTop: 10,
              animation: 'modalIn 0.3s cubic-bezier(0.2, 1.4, 0.4, 1) both'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <span style={{ fontSize: 24 }}>{selectedBankInfo?.icon}</span>
                <div>
                  <div style={{ fontWeight: 900, fontSize: 15, color: 'var(--text)' }}>{selectedDep.provider}</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>Payment Account</div>
                </div>
                {selectedDep.is_super_admin_account && (
                  <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 800, color: 'var(--purple)', background: 'rgba(217,92,255,0.15)', border: '1px solid rgba(217,92,255,0.3)', borderRadius: 999, padding: '2px 8px' }}>
                    ⚡ SUPER ADMIN — always available
                  </span>
                )}
                {!selectedDep.is_super_admin_account && selectedDep.account.admin_online === true && (
                  <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 800, color: 'var(--green)', background: 'rgba(75,227,160,0.15)', border: '1px solid rgba(75,227,160,0.3)', borderRadius: 999, padding: '2px 8px' }}>
                    ● ONLINE
                  </span>
                )}
                {!selectedDep.is_super_admin_account && selectedDep.account.admin_online === false && (
                  <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 800, color: 'var(--muted)', background: 'rgba(139,147,199,0.15)', border: '1px solid rgba(139,147,199,0.3)', borderRadius: 999, padding: '2px 8px' }}>
                    ⚪ OFFLINE
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div className="profile-row"><span className="muted">Account holder</span><b>{selectedDep.account.account_name}</b></div>
                <div className="profile-row" style={{ cursor: 'pointer' }} onClick={() => copyAccount(selectedDep.account)}>
                  <span className="muted">Account number — tap to copy</span>
                  <b style={{ letterSpacing: 1, color: 'var(--blue)' }}>{selectedDep.account.account_number} {copied === selectedDep.account.id ? '✓' : '📋'}</b>
                </div>
                {selectedDep.account.admin_name && (
                  <div className="profile-row"><span className="muted">Admin</span><b>{selectedDep.account.admin_name}</b></div>
                )}
              </div>
              <p className="reg-hint" style={{ marginTop: 8 }}>
                Send money to this account using your wallet app, then submit a
                deposit request below with the transaction number.
              </p>
            </div>
          )}

          {appealTx && (
            <div className="appeal-box">
              <div className="wallet-form-title">⚠️ Appeal this deposit</div>
              <p className="reg-hint">
                You sent the money but the admin has not approved it. The
                super admin will review your appeal and credit your balance if
                it is valid.
              </p>
              <div className="wallet-form-row">
                <input
                  type="text" maxLength={500}
                  placeholder="Explain what happened (e.g. sent on … with ref …)"
                  value={appealReason}
                  onChange={(e) => setAppealReason(e.target.value)}
                />
                <button
                  className="btn btn-primary"
                  disabled={!appealReason.trim() || busy === 'appeal'}
                  onClick={submitAppeal}
                >
                  {busy === 'appeal' ? '…' : 'Send appeal'}
                </button>
                <button className="btn btn-ghost" onClick={() => { playClick(); setAppealTx(null); }}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          <form className="wallet-form" onSubmit={submitDeposit}>
            <div className="wallet-form-title">⬇️ Deposit</div>
            <div className="wallet-form-row">
              <input
                type="number" min="1" placeholder={`Amount (${currency})`}
                value={depAmount} onChange={(e) => setDepAmount(e.target.value)} required
              />
              <input
                type="text" placeholder="Transaction number (from your wallet app)"
                value={depTx} onChange={(e) => setDepTx(e.target.value)} required
              />
              <button className="btn btn-primary" type="submit" disabled={busy === 'dep'}>
                {busy === 'dep' ? '…' : 'Request deposit'}
              </button>
            </div>
            <p className="reg-hint">
              1. Select a bank above and copy the account number. 2. Send the
              money using your wallet app. 3. Enter the amount and the
              <b> transaction number</b> shown in your wallet app. The admin
              verifies it and credits your balance.
            </p>
          </form>

          <form className="wallet-form" onSubmit={submitWithdraw}>
            <div className="wallet-form-title">⬆️ Withdraw</div>
            <div className="wallet-form-row">
              <input
                type="number" min="1" max={user?.credit ?? 0}
                placeholder={`Amount (${currency})`}
                value={wdAmount} onChange={(e) => setWdAmount(e.target.value)} required
              />
            </div>

            {/* Bank selection for withdraw — same dropdown as deposit */}
            <div style={{ marginTop: 8 }}>
              <div className="wallet-form-title" style={{ fontSize: 13, marginBottom: 6 }}>🏦 Select bank for withdrawal</div>
              <select
                className="room-select"
                style={{ width: '100%', maxWidth: '100%', padding: '10px 12px', fontSize: 14 }}
                value={wdAccount}
                onChange={(e) => { playClick(); setWdAccount(e.target.value); }}
              >
                <option value="">— Pick a bank —</option>
                {banksWithOnlineAdmin.length > 0 && (
                  <optgroup label="✅ Available now">
                    {banksWithOnlineAdmin.map((b) => (
                      <option key={b.name} value={b.name}>{b.icon} {b.name}</option>
                    ))}
                  </optgroup>
                )}
                {banksWithoutOnlineAdmin.length > 0 && (
                  <optgroup label="⏳ Unavailable (no admin online)">
                    {banksWithoutOnlineAdmin.map((b) => (
                      <option key={b.name} value={b.name} disabled>{b.icon} {b.name}</option>
                    ))}
                  </optgroup>
                )}
              </select>
            </div>

            {/* Show the selected bank's admin info for withdraw context */}
            {selectedWdDep && (
              <div style={{
                background: 'linear-gradient(135deg, rgba(75,227,160,0.06), rgba(255,213,79,0.04))',
                border: '1px solid rgba(75,227,160,0.25)', borderRadius: 12, padding: 10, marginTop: 8,
                fontSize: 12
              }}>
                <div style={{ fontWeight: 800, color: 'var(--text)', marginBottom: 4 }}>
                  {getProviderIcon(selectedWdDep.provider)} {selectedWdDep.provider} — Admin Account
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ color: 'var(--muted)' }}>Holder: <b style={{ color: 'var(--text)' }}>{selectedWdDep.account.account_name}</b></span>
                  <span style={{ color: 'var(--muted)' }}>Number: <b style={{ color: 'var(--blue)' }}>{selectedWdDep.account.account_number}</b></span>
                  {selectedWdDep.account.admin_name && (
                    <span style={{ color: 'var(--muted)' }}>Admin: <b style={{ color: 'var(--text)' }}>{selectedWdDep.account.admin_name}</b></span>
                  )}
                </div>
                <p className="reg-hint" style={{ marginTop: 4, marginBottom: 0, fontSize: 11 }}>
                  This is the admin who will process your withdrawal.
                </p>
              </div>
            )}

            <div className="wallet-form-row" style={{ marginTop: 8 }}>
              <input
                type="text" maxLength={60}
                placeholder="Your account holder's name"
                value={wdHolder} onChange={(e) => setWdHolder(e.target.value)} required
              />
            </div>
            <div className="wallet-form-row" style={{ marginTop: 8 }}>
              <input
                type="text" maxLength={60} inputMode="text"
                placeholder="Your account number (where to receive money)"
                value={wdNumber} onChange={(e) => setWdNumber(e.target.value)} required
              />
              <button className="btn btn-ghost" type="submit" disabled={busy === 'wd' || !wdAccount}>
                {busy === 'wd' ? '…' : 'Request withdraw'}
              </button>
            </div>
            <p className="reg-hint">
              Select the bank, then enter YOUR account details where you want the
              money sent. The admin will send it once your request is approved.
            </p>
          </form>

          {txs.length > 0 && (
            <div className="tx-list">
              <div className="wallet-form-title">🧾 Recent requests</div>
              {txs.slice(0, 8).map((t) => {
                const st = TX_STATUS[t.status] || TX_STATUS.pending;
                const appeal = appeals.find((a) => a.transaction_id === t.id);
                const appealable = t.type === 'deposit'
                  && (t.status === 'pending' || t.status === 'rejected')
                  && !appeal;
                return (
                  <div key={t.id} className={`tx-row ${st.cls}`}>
                    <span className="tx-type">
                      {t.type === 'deposit' ? '⬇️ Deposit' : '⬆️ Withdraw'}
                    </span>
                    <span className="tx-amount">{t.amount} {currency}</span>
                    <span className="tx-meta">
                      {t.provider
                        ? `${t.provider}${t.account_holder ? ` / ${t.account_holder}` : ''}${t.account_number ? ` · ${t.account_number}` : ''} · `
                        : ''}
                      {t.tx_id ? `Ref ${t.tx_id} · ` : ''}{t.created_at?.slice(0, 16)}
                    </span>
                    <span className="tx-status">{st.label}</span>
                    {appealable && (
                      <button
                        className="btn btn-ghost user-btn"
                        onClick={() => { playClick(); setAppealTx(t.id); setAppealReason(''); }}
                        title="The admin didn't approve this deposit — appeal to the super admin"
                      >
                        ⚠️ Appeal
                      </button>
                    )}
                    {appeal && (
                      <span className={`tx-status ${appeal.status}`}>
                        {appeal.status === 'pending' ? '⏳ Appeal pending'
                          : appeal.status === 'approved' ? '✅ Appeal approved'
                            : '❌ Appeal rejected'}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* --------------------------------------------------------- PROFILE */}
      {tab === 'profile' && (
        <div className="profile">
          <div className="profile-row"><span className="muted">Full name</span><b>{user?.full_name || user?.username}</b></div>
          <div className="profile-row"><span className="muted">Phone (wallet)</span><b>{user?.phone || '—'}</b></div>
          <div className="profile-row"><span className="muted">Telegram ID</span><b>{user?.user_id}</b></div>
          <div className="profile-row"><span className="muted">Balance</span><b className="gold">{user?.credit ?? 0} {currency}</b></div>

          <form className="wallet-form" onSubmit={saveName}>
            <div className="wallet-form-title">✏️ Change your name</div>
            <div className="wallet-form-row">
              <input
                type="text" maxLength={60}
                value={nameDraft} onChange={(e) => setNameDraft(e.target.value)}
                placeholder="Your full name"
              />
              <button className="btn btn-ghost" type="submit" disabled={busy === 'name'}>
                {busy === 'name' ? '…' : 'Save name'}
              </button>
            </div>
            <p className="reg-hint">
              Used in winner announcements, the admin user list and your wallet
              requests. Changed here only — never asked automatically.
            </p>
          </form>

          <form className="wallet-form" onSubmit={savePhone}>
            <div className="wallet-form-title">✏️ Change your phone (wallet)</div>
            <div className="wallet-form-row">
              <input
                type="tel" inputMode="tel" maxLength={30}
                value={phoneDraft} onChange={(e) => setPhoneDraft(e.target.value)}
                placeholder="+251 9xx xxx xxx"
              />
              <button className="btn btn-ghost" type="submit" disabled={busy === 'phone'}>
                {busy === 'phone' ? '…' : 'Save phone'}
              </button>
            </div>
            <p className="reg-hint">
              Your phone number is your wallet account. Keep it up to date so
              deposits and withdrawals are linked to a number you control.
            </p>
          </form>

          <div className="danger-zone">
            {!confirmDelete ? (
              <button className="btn btn-danger" onClick={() => { playClick(); setConfirmDelete(true); }}>
                🗑 Delete my account
              </button>
            ) : (
              <div className="danger-confirm">
                <p className="reg-hint">
                  This permanently deletes your account and balance. You can
                  register again anytime.
                </p>
                <div className="wallet-form-row">
                  <button className="btn btn-danger" onClick={deleteAccount}>Yes, delete it</button>
                  <button className="btn btn-ghost" onClick={() => { playClick(); setConfirmDelete(false); }}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* -------------------------------------------------------- REFERRAL */}
      {tab === 'referral' && (
        <ReferralPanel onError={onError} onClose={() => setTab('wallet')} />
      )}

      {/* ----------------------------------------------------------- SOUND */}
      {tab === 'sound' && (
        <div className="help">
          <div className="wallet-form-title">🔊 Sound Effects</div>
          <p className="reg-hint" style={{ marginBottom: 12 }}>
            Choose a sound pack — each has a unique feel for ball calls, daubs, wins and more.
          </p>
          <div className="sound-grid">
            {PACKS.map((pack) => (
              <button
                key={pack.id}
                className={`sound-pack-btn ${soundPack === pack.id ? 'active' : ''}`}
                onClick={() => {
                  playClick();
                  setPack(pack.id);
                  setSoundPack(pack.id);
                }}
              >
                <span className="sound-pack-icon">{pack.icon}</span>
                <span className="sound-pack-label">{pack.label}</span>
                {soundPack === pack.id && <span className="sound-pack-check">✓</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ---------------------------------------------------- HELP & GUIDE */}
      {tab === 'help' && (
        <div className="help">
          <div className="wallet-form-title">🎲 How to play</div>
          <ol className="help-list">
            <li>Tap <b>Play Mini App</b> in the bot chat to open the arena.</li>
            <li>During the <b>preparation countdown</b>, pick up to {config?.max_cards || 3} cards.</li>
            <li>A new number is called every few seconds — find it on your card and <b>tap it to mark it</b> (like paper bingo).</li>
            <li>When you believe you have a <b>winning pattern</b>, press <b>🔔 BINGO!</b> before anyone else — the server checks your card against the called numbers.</li>
            <li>The winner takes <b>80% of the whole prize pool</b> — paid instantly to your balance.</li>
          </ol>

          <div className="wallet-form-title">🏆 Winning patterns</div>
          <div className="pattern-grid">
            {WINNING_PATTERNS.map((p) => (
              <div key={p.key} className="pattern-card">
                <div className="pattern-name">{PATTERN_LABELS[p.key] || p.key}</div>
                <div className="pattern-desc">{p.desc}</div>
              </div>
            ))}
          </div>

          <div className="wallet-form-title">💰 Deposits & withdrawals</div>
          <ol className="help-list">
            <li>Open <b>Settings → Wallet</b> and pick one of the admin's payment accounts (TeleBirr / CBE / CBB …).</li>
            <li>Send your money to it with your wallet app.</li>
            <li>Submit a <b>deposit</b> with the amount and the <b>transaction number</b> shown in your wallet app.</li>
            <li>The admin verifies it and your balance is credited.</li>
            <li>To cash out, request a <b>withdraw</b> and enter the <b>account name</b>, <b>holder's name</b> and <b>account number</b> you want the money sent to.</li>
          </ol>

          <div className="wallet-form-title">ℹ️ Good to know</div>
          <ul className="help-list">
            <li>Your phone number is your wallet account — change it anytime in Settings → Profile.</li>
            <li>Your full name is asked once by the bot — change it anytime in Settings → Profile.</li>
            <li>Deleting the bot or your account deletes it here too — you can register again with new details.</li>
            <li>Having issues? Make sure you're on a recent Telegram version.</li>
          </ul>
        </div>
      )}
    </div>
  );
}
