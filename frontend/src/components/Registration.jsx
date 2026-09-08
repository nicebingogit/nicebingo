import { useState } from 'react';
import { api } from '../api.js';
import { isTelegram, requestPhoneContact } from '../telegram.js';
import { playClick } from '../sound.js';

// First-time onboarding — shown before any gameplay when the account is not
// fully registered. The FULL NAME is collected ONCE by the bot in the chat
// (send /start, type your name) — the Mini App never asks for it again. Here
// we only add the phone number (the wallet account):
//   * inside Telegram -> the native "Share phone number" dialog fills the
//     phone automatically (Telegram.WebApp.requestContact);
//   * anywhere else   -> a manual phone input appears instead.
// If the bot hasn't collected a name yet, the user is sent to the chat first
// (the Mini App must not bypass the required name onboarding).
export default function Registration({ user, onDone, onError }) {
  const [phone, setPhone] = useState('');
  const [phoneAuto, setPhoneAuto] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const hasName = !!((user?.full_name || '').trim());

  if (!hasName) {
    return (
      <div className="registration">
        <div className="reg-card">
          <div className="reg-logo">🎰 NICE BINGO</div>
          <h1 className="reg-title">One quick step first ✍️</h1>
          <p className="reg-sub">
            To create your account, open the <b>Nice Bingo bot chat</b>, send{' '}
            <b>/start</b> and type your <b>full name</b> when the bot asks for
            it. Then come back here and tap the button below.
          </p>
          <button
            className="btn btn-primary reg-submit"
            onClick={() => { playClick(); onDone(); }}
          >
            🔄 I've entered my name
          </button>
          <p className="reg-terms">
            Your full name is your identity in winner announcements and your
            wallet — it is collected once and can be changed later in Settings.
          </p>
        </div>
      </div>
    );
  }

  const sharePhone = async () => {
    playClick();
    setMsg('Waiting for Telegram…');
    const p = await requestPhoneContact();
    if (p) {
      setPhone(p);
      setPhoneAuto(true);
      setMsg(`✅ Phone shared: ${p}`);
    } else {
      setPhoneAuto(false);
      setMsg('Could not share automatically — please type your phone number below.');
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!phone.trim()) {
      setMsg('❌ A phone number is required (used as your wallet account).');
      return;
    }
    playClick();
    setBusy(true);
    setMsg('');
    try {
      await api.register(phone.trim().replace(/\s+/g, ''));
      onDone();
    } catch (err) {
      setMsg(`❌ ${err.message}`);
      onError?.(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="registration">
      <div className="reg-card">
        <div className="reg-logo">🎰 NICE BINGO</div>
        <h1 className="reg-title">Almost there!</h1>
        <p className="reg-sub">
          Just add your phone number — it becomes your wallet for deposits and
          withdrawals.
        </p>

        <div className="reg-name-line">👤 <b>{user.full_name}</b></div>

        <form onSubmit={submit} className="reg-form">
          <label className="reg-field">
            <span className="reg-label">Phone number (wallet account)</span>
            <div className="reg-phone-row">
              <input
                type="tel"
                placeholder="+251 9xx xxx xxx"
                value={phone}
                onChange={(e) => { setPhone(e.target.value); setPhoneAuto(false); }}
                autoComplete="tel"
                inputMode="tel"
                maxLength={20}
              />
              {isTelegram && (
                <button type="button" className="btn btn-ghost" onClick={sharePhone} disabled={busy}>
                  📱 Share
                </button>
              )}
            </div>
            {phoneAuto && <span className="reg-ok">✓ Shared automatically by Telegram</span>}
            {!phoneAuto && isTelegram && (
              <span className="reg-hint">or tap 📱 Share and Telegram fills it in for you</span>
            )}
          </label>

          {msg && <div className="reg-msg">{msg}</div>}

          <button className="btn btn-primary reg-submit" type="submit" disabled={busy}>
            {busy ? 'Creating account…' : '🚀 Start playing'}
          </button>
          <p className="reg-terms">
            By continuing you agree to play responsibly. Credits are in-game
            balance — this is entertainment.
          </p>
        </form>
      </div>
    </div>
  );
}
