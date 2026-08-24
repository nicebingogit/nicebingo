import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { playClick } from '../sound.js';

const COPY_RESET_MS = 2500;

export default function ReferralPanel({ onError, onClose }) {
  const [stats, setStats] = useState(null);
  const [commissions, setCommissions] = useState([]);
  const [leaders, setLeaders] = useState([]);
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState('overview');
  const [flash, setFlash] = useState('');

  const loadData = useCallback(async () => {
    try {
      const [s, c, l] = await Promise.all([
        api.referralLink(),
        api.referralCommissions(),
        api.referralLeaderboard(),
      ]);
      setStats(s);
      setCommissions(c.commissions || []);
      setLeaders(l.leaders || []);
    } catch (e) {
      onError?.(e.message);
    }
  }, [onError]);

  useEffect(() => { loadData(); }, [loadData]);

  const refLink = stats
    ? `https://t.me/${window.__bot_username || 'YourBot'}?start=REF_${stats.referrer_id}`
    : '';

  const copyLink = async () => {
    playClick();
    try {
      // Try the Telegram WebApp clipboard API first (works in Mini App)
      if (window.Telegram?.WebApp?.clipboard) {
        window.Telegram.WebApp.clipboard.writeText(refLink);
      } else {
        await navigator.clipboard.writeText(refLink);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), COPY_RESET_MS);
    } catch {
      // fallback: select + execCommand
      try {
        const ta = document.createElement('textarea');
        ta.value = refLink;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        setCopied(true);
        setTimeout(() => setCopied(false), COPY_RESET_MS);
      } catch {
        flash('Could not copy — please copy manually.');
      }
    }
  };

  const shareLink = () => {
    playClick();
    const text = encodeURIComponent(
      `🎰 Join Nice Bingo and play with me! Use my referral link:\n${refLink}`
    );
    window.open(`https://t.me/share/url?url=${text}`, '_blank');
  };

  if (!stats) {
    return (
      <div className="panel referral-panel">
        <div className="picker-title">🔗 Referral Program</div>
        <div className="muted">Loading referral data…</div>
      </div>
    );
  }

  const myRank = leaders.findIndex((l) => l.user_id === stats.referrer_id) + 1;

  return (
    <div className="panel referral-panel">
      <div className="settings-head">
        <div className="picker-title">🔗 Referral Program</div>
        <button className="chip chip-btn" onClick={() => { playClick(); onClose(); }}>✕ Close</button>
      </div>

      {flash && <div className="admin-flash">{flash}</div>}

      <div className="settings-tabs">
        {[
          ['overview', '📊 Overview'],
          ['link', '🔗 My Link'],
          ['commissions', '💰 Commissions'],
          ['leaderboard', '🏆 Leaderboard'],
          ['users', '👥 My Referrals'],
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

      {/* ------------------------------------------------------- OVERVIEW */}
      {tab === 'overview' && (
        <div className="referral-overview">
          <div className="referral-hero">
            <div className="referral-hero-icon">💰</div>
            <div className="referral-hero-title">Earn 5% Commission</div>
            <div className="referral-hero-sub">
              Every time someone you invited plays a round, you earn 5% of their total bet!
            </div>
          </div>

          <div className="referral-stats-grid">
            <div className="referral-stat-card">
              <div className="referral-stat-icon">👥</div>
              <div className="referral-stat-value">{stats.total_referrals}</div>
              <div className="referral-stat-label">Total Referrals</div>
            </div>
            <div className="referral-stat-card gold">
              <div className="referral-stat-icon">🎮</div>
              <div className="referral-stat-value">{stats.active_referrals}</div>
              <div className="referral-stat-label">Active Players</div>
            </div>
            <div className="referral-stat-card accent">
              <div className="referral-stat-icon">💎</div>
              <div className="referral-stat-value">{stats.total_commission}</div>
              <div className="referral-stat-label">ETB Earned</div>
            </div>
            {myRank > 0 && (
              <div className="referral-stat-card purple">
                <div className="referral-stat-icon">🏆</div>
                <div className="referral-stat-value">#{myRank}</div>
                <div className="referral-stat-label">Your Rank</div>
              </div>
            )}
          </div>

          {/* Quick share buttons */}
          <div className="referral-actions">
            <button className="btn btn-primary" onClick={copyLink}>
              {copied ? '✅ Copied!' : '📋 Copy Referral Link'}
            </button>
            <button className="btn btn-ghost" onClick={shareLink}>
              📤 Share on Telegram
            </button>
          </div>

          {/* How it works */}
          <div className="referral-howto">
            <div className="wallet-form-title">🎯 How It Works</div>
            <div className="referral-steps">
              <div className="referral-step">
                <div className="referral-step-num">1</div>
                <div className="referral-step-text">
                  <b>Share your link</b> — send it to friends, post it in groups, or share on social media.
                </div>
              </div>
              <div className="referral-step">
                <div className="referral-step-num">2</div>
                <div className="referral-step-text">
                  <b>They join & play</b> — when someone clicks your link and registers, they're linked to you forever.
                </div>
              </div>
              <div className="referral-step">
                <div className="referral-step-num">3</div>
                <div className="referral-step-text">
                  <b>You earn 5%</b> — every round they play, you automatically get 5% of their total bet added to your balance!
                </div>
              </div>
            </div>
            <div className="referral-example">
              <div className="wallet-form-title" style={{ fontSize: 12 }}>💡 Example</div>
              <p className="reg-hint">
                If your referral bets <b>30 ETB</b> on a card, you earn <b>1.5 ETB</b>. If they play 10 rounds, that's <b>15 ETB</b> — all passive income! No limit on referrals or earnings.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------- MY LINK */}
      {tab === 'link' && (
        <div className="referral-link-tab">
          <div className="referral-link-card">
            <div className="referral-link-label">Your unique referral link</div>
            <div className="referral-link-url" onClick={copyLink}>
              {refLink}
              <span className="referral-link-copy-hint">
                {copied ? '✅ Copied!' : '📋 Tap to copy'}
              </span>
            </div>
            <div className="referral-actions" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" onClick={copyLink}>
                {copied ? '✅ Copied!' : '📋 Copy Link'}
              </button>
              <button className="btn btn-ghost" onClick={shareLink}>
                📤 Share on Telegram
              </button>
            </div>
          </div>

          <div className="referral-howto">
            <div className="wallet-form-title">📤 Share Methods</div>
            <ul className="help-list">
              <li><b>Telegram:</b> Tap "Share on Telegram" above — sends to any chat or channel.</li>
              <li><b>Copy & Paste:</b> Copy the link and paste it anywhere — WhatsApp, Facebook, SMS, email.</li>
              <li><b>QR Code:</b> The link works as a deep link — anyone who opens it in Telegram is automatically referred to you.</li>
              <li><b>Groups:</b> Share in Telegram groups to reach more people at once.</li>
            </ul>
          </div>
        </div>
      )}

      {/* --------------------------------------------------- COMMISSIONS */}
      {tab === 'commissions' && (
        <div className="referral-commissions">
          {commissions.length === 0 ? (
            <div className="muted" style={{ padding: 20, textAlign: 'center' }}>
              No commissions yet. Share your referral link to start earning!
            </div>
          ) : (
            <div className="tx-list">
              <div className="wallet-form-title">💎 Recent Commissions</div>
              {commissions.map((c) => (
                <div key={c.id} className="tx-row approved">
                  <span className="tx-type">💰 Commission</span>
                  <span className="tx-amount" style={{ color: 'var(--green)' }}>
                    +{c.commission} ETB
                  </span>
                  <span className="tx-meta">
                    <b>{c.referred_name || c.referred_username || `#${c.referred_id}`}</b>
                    {' · '}{c.total_bet} ETB bet
                    {' · '}{c.room} ETB room
                    {' · '}{c.created_at?.slice(0, 16)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* -------------------------------------------------- LEADERBOARD */}
      {tab === 'leaderboard' && (
        <div className="referral-leaderboard">
          {leaders.length === 0 ? (
            <div className="muted" style={{ padding: 20, textAlign: 'center' }}>
              No referral commissions recorded yet.
            </div>
          ) : (
            <div className="user-list">
              <div className="wallet-form-title">🏆 Top Referrers</div>
              {leaders.map((l, i) => {
                const medals = ['🥇', '🥈', '🥉'];
                const medal = medals[i] || `${i + 1}.`;
                const isMe = l.user_id === stats?.referrer_id;
                return (
                  <div
                    key={l.user_id}
                    className={`user-row ${isMe ? 'highlight' : ''}`}
                    style={isMe ? { border: '1px solid var(--gold)', borderRadius: 12 } : {}}
                  >
                    <div className="user-info">
                      <div className="user-name">
                        {medal} {l.full_name || l.username || `User #${l.user_id}`}
                        {isMe && <span className="user-badge" style={{ background: 'var(--gold)', color: '#000' }}>YOU</span>}
                      </div>
                      <div className="user-meta">
                        {l.active_referrals} active referrals
                      </div>
                    </div>
                    <div className="user-credit">
                      <b className="gold">{l.total_commission} ETB</b>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* -------------------------------------------------- MY REFERRALS */}
      {tab === 'users' && (
        <div className="referral-users">
          {(stats.referred_users || []).length === 0 ? (
            <div className="muted" style={{ padding: 20, textAlign: 'center' }}>
              No referrals yet. Share your link to get started!
            </div>
          ) : (
            <div className="user-list">
              <div className="wallet-form-title">👥 Your Referrals ({stats.referred_users.length})</div>
              {stats.referred_users.map((u) => (
                <div key={u.referred_id} className="user-row">
                  <div className="user-info">
                    <div className="user-name">
                      {u.full_name || u.username || `User #${u.referred_id}`}
                    </div>
                    <div className="user-meta">
                      ID: {u.referred_id} · Joined: {u.joined_at?.slice(0, 10)}
                    </div>
                  </div>
                  <div className="user-credit">
                    <b className="gold">{u.credit} ETB</b>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
