import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { playClick } from '../sound.js';
import { PATTERN_LABELS } from '../bingo.js';

const TX_STATUS = {
  pending: { label: '⏳ Pending', cls: 'pending' },
  approved: { label: '✅ Approved', cls: 'approved' },
  rejected: { label: '❌ Rejected', cls: 'rejected' },
};

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

  // wallet appeals: a deposit the admin never approved can be appealed to the
  // SUPER ADMIN
  const [appeals, setAppeals] = useState([]);
  const [appealTx, setAppealTx] = useState(null);
  const [appealReason, setAppealReason] = useState('');

  // deposit_accounts = ONE account per bank/provider — always the account of
  // the ONLINE admin with the most credit; offline admins' accounts are never
  // listed
  const depositAccounts = settings?.deposit_accounts || [];
  const selectedDep = depositAccounts.find((d) => d.provider === depProvider) || null;
  const accId = selectedDep ? selectedDep.account.id : null;

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

  // default the deposit picker to the first available bank
  useEffect(() => {
    if (!depProvider && depositAccounts.length) {
      setDepProvider(depositAccounts[0].provider);
    }
  }, [depositAccounts, depProvider]);

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
          <div className="wallet-balance">
            <span className="wallet-balance-label">Your balance</span>
            <span className="wallet-balance-num">
              {user?.credit ?? 0} <small>{currency}</small>
            </span>
          </div>

          {depositAccounts.length === 0 ? (
            <div className="reg-hint">
              ⏳ No payment account is available right now — every admin is
              offline. Check again in a few minutes.
            </div>
          ) : (
            <div className="acc-picker">
              <div className="wallet-form-title">💳 Where can you pay?</div>
              {/* one account per bank — always the ONLINE admin with the most
                  credit; offline admins' accounts are never shown */}
              {depositAccounts.map((d) => (
                <label
                  key={d.provider}
                  className={`acc-option ${depProvider === d.provider ? 'selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="payacc"
                    checked={depProvider === d.provider}
                    onChange={() => setDepProvider(d.provider)}
                  />
                  <span className="acc-provider">{d.provider}</span>
                  <span className="acc-holder">— {d.account.account_name}</span>
                  <span className="acc-number">{d.account.account_number}</span>
                  <button
                    type="button"
                    className="chip chip-btn acc-copy"
                    onClick={() => copyAccount(d.account)}
                    title="Copy number"
                  >
                    {copied === d.account.id ? '✓' : '📋'}
                  </button>
                </label>
              ))}
              {selectedDep && selectedDep.account.admin_name && (
                <p className="reg-hint">
                  👤 Online admin: <b>{selectedDep.account.admin_name}</b> — this
                  is the only {selectedDep.provider} account available right now.
                </p>
              )}
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
              1. Select the account you paid into above. 2. Enter the amount and
              the <b>transaction number</b> shown in your wallet app. The admin
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
            <div className="wallet-form-row" style={{ marginTop: 8 }}>
              <input
                type="text" maxLength={60}
                placeholder="Account name (TeleBirr, CBE, CBB…)"
                value={wdAccount} onChange={(e) => setWdAccount(e.target.value)} required
              />
              <input
                type="text" maxLength={60}
                placeholder="Account holder's name"
                value={wdHolder} onChange={(e) => setWdHolder(e.target.value)} required
              />
            </div>
            <div className="wallet-form-row" style={{ marginTop: 8 }}>
              <input
                type="text" maxLength={60} inputMode="text"
                placeholder="Account number"
                value={wdNumber} onChange={(e) => setWdNumber(e.target.value)} required
              />
              <button className="btn btn-ghost" type="submit" disabled={busy === 'wd'}>
                {busy === 'wd' ? '…' : 'Request withdraw'}
              </button>
            </div>
            <p className="reg-hint">
              Enter the account your winnings should be sent to — the admin
              pays these exact details once your request is approved.
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
