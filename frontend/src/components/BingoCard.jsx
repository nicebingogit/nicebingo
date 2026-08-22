import { LETTERS, cellKey } from '../bingo.js';
import { COLORS } from './CalledBoard.jsx';

// MANUAL play: the called board shows which numbers were drawn, but the player
// must find and TAP each one on their own card to mark it (paper-bingo style).
// `markedSet` is the player's own set of marked keys ("B-7", "N-44", …) — purely
// client-side. The SERVER verifies the claim against the real called numbers.
// When `interactive` is false the card is read-only (e.g. after a false-BINGO
// elimination — the player can still SEE their card but cannot play).
export default function BingoCard({
  card,
  markedSet = new Set(),
  winCells = [],
  size = 'normal',
  interactive = false,
  onToggleCell,
  spectator = false,
  calledNumbers = [],
}) {
  const winSet = new Set(winCells.map(([c, r]) => `${c},${r}`));
  const numbers = card.numbers || {};
  const isWinning = winCells.length > 0;
  // In spectator mode, auto-mark cells that match called numbers
  const spectatorSet = spectator ? new Set(calledNumbers) : null;

  return (
    <div className={`bingo-card ${size} ${isWinning ? 'winning' : ''}`}>
      <div className="card-head">
        <span className="card-id">🎯 Card {card.card_id}</span>
        <span className="card-bet">{card.bet_amount} ETB</span>
      </div>
      <div className="card-grid">
        <div className="card-row card-headrow">
          {LETTERS.map((l) => (
            <div key={l} className="card-cell head" style={{ color: COLORS[l] }}>{l}</div>
          ))}
        </div>
        {[0, 1, 2, 3, 4].map((row) => (
          <div className="card-row" key={row}>
            {LETTERS.map((letter, col) => {
              const value = numbers[letter]?.[row];
              const free = value === 'FREE';
              const marked = free || (spectatorSet ? spectatorSet.has(cellKey(letter, value)) : markedSet.has(cellKey(letter, value)));
              const winning = winSet.has(`${col},${row}`);
              return (
                <button
                  key={`${letter}${row}`}
                  type="button"
                  className={`card-cell ${free ? 'free' : ''} ${marked && !free ? 'marked' : ''} ${winning ? 'winning' : ''} ${interactive && !free ? 'daubable' : ''}`}
                  onClick={interactive && !free ? () => onToggleCell?.(letter, value) : undefined}
                  disabled={!interactive || free}
                  title={interactive && !free ? 'Tap to mark / unmark this number' : undefined}
                >
                  {free ? '★' : marked ? '●' : value}
                </button>
              );
            })}
          </div>
        ))}
      </div>
      {isWinning && <div className="card-badge">🏆 BINGO!</div>}
    </div>
  );
}
