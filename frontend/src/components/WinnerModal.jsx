import { useEffect, useMemo } from 'react';
import { playClick } from '../sound.js';
import { haptic } from '../telegram.js';
import { PATTERN_LABELS, LETTERS } from '../bingo.js';
import { COLORS } from './CalledBoard.jsx';

const CONFETTI_COLORS = ['#ff5f7a', '#ffd54f', '#4be3a0', '#3ec8ff', '#d95cff', '#ffb74d', '#ffffff'];

// The winner's card with their winning pattern DRAWN on it — every player
// (winner and losers) sees exactly which cells made the BINGO, glowing gold.
function WinningPatternCard({ card, cells, pattern }) {
  const winSet = useMemo(() => new Set((cells || []).map(([c, r]) => `${c},${r}`)), [cells]);
  const numbers = card?.numbers || {};
  if (!card) return null;
  return (
    <div className="winner-card-wrap">
      <div className="winner-card">
        <div className="winner-card-head">
          {LETTERS.map((l) => (
            <span key={l} style={{ color: COLORS[l], textShadow: `0 0 10px ${COLORS[l]}66` }}>{l}</span>
          ))}
        </div>
        {[0, 1, 2, 3, 4].map((row) => (
          <div className="winner-card-row" key={row}>
            {LETTERS.map((letter, col) => {
              const value = numbers[letter]?.[row];
              const free = value === 'FREE';
              const isWin = winSet.has(`${col},${row}`);
              return (
                <span
                  key={`${letter}${row}`}
                  className={`winner-cell ${free ? 'free' : ''} ${isWin ? 'hit' : 'miss'}`}
                >
                  {free ? '★' : value}
                </span>
              );
            })}
          </div>
        ))}
      </div>
      <div className="winner-pattern-tag">✨ {PATTERN_LABELS[pattern] || pattern || 'BINGO'}</div>
    </div>
  );
}

export default function WinnerModal({ winner, myId, onClose }) {
  const iWon = winner && winner.user_id === myId;
  const confetti = useMemo(
    () =>
      Array.from({ length: 70 }, (_, i) => ({
        id: i,
        left: Math.random() * 100,
        delay: Math.random() * 2.5,
        dur: 2.8 + Math.random() * 2.2,
        color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
        size: 6 + Math.random() * 7,
        rot: Math.random() * 360,
      })),
    [],
  );

  // the winning moment ALWAYS vibrates — success for the winner, a warning
  // nudge for everyone else (some clients miss the sound on mute)
  useEffect(() => {
    haptic(iWon ? 'success' : 'warning');
  }, [iWon]);

  return (
    <div className="modal-overlay">
      <div className="confetti">
        {confetti.map((c) => (
          <span
            key={c.id}
            className="confetti-piece"
            style={{
              left: `${c.left}%`,
              width: c.size,
              height: c.size * 0.45,
              background: c.color,
              animationDelay: `${c.delay}s`,
              animationDuration: `${c.dur}s`,
              transform: `rotate(${c.rot}deg)`,
            }}
          />
        ))}
      </div>

      <div className={`modal-card ${iWon ? 'won' : 'lost'}`}>
        <div className="trophy">{iWon ? '🏆' : '💔'}</div>
        <h2>{iWon ? 'BINGO! BINGO! BINGO!' : 'So close!'}</h2>
        {iWon ? (
          <>
            <p className="modal-pattern">
              Winning pattern: <b>{PATTERN_LABELS[winner.pattern] || winner.pattern}</b>
            </p>
            <div className="prize-box">
              <span className="prize-amount">+{winner.prize}</span>
              <span className="prize-currency">ETB</span>
            </div>
            <p className="muted">Paid instantly to your balance 🎉</p>
          </>
        ) : (
          <>
            {/* everyone sees the winner's name AND winning pattern */}
            <p className="modal-pattern">
              🏆 {winner?.name || 'Someone'} won with{' '}
              <b>{PATTERN_LABELS[winner?.pattern] || winner?.pattern}</b>
            </p>
            <div className="prize-box">
              <span className="prize-amount">{winner?.prize ?? 0}</span>
              <span className="prize-currency">ETB</span>
            </div>
          </>
        )}

        {/* the winning pattern DRAWN on the winner's card — for everyone */}
        <WinningPatternCard card={winner?.card} cells={winner?.winning_cells} pattern={winner?.pattern} />

        {!iWon && <p className="modal-next">New round starts in a few seconds — grab your cards!</p>}
        <button className="btn btn-primary" onClick={() => { playClick(); onClose(); }}>
          Nice!
        </button>
      </div>
    </div>
  );
}
