import { PACKS, getPack } from '../sound.js';

export default function Header({ credit, pool, room, rooms, onRoomChange, isAdmin, isSuperAdmin, showAdmin, showSuper, onToggleAdmin, onToggleSuper, onToggleSettings, connected, phase, realPlayers, cardsInPlay }) {
  const packIdx = PACKS.findIndex((p) => p.id === getPack());
  const currentPack = PACKS[packIdx] || PACKS[0];
  const isPlaying = phase === 'playing' || phase === 'ended';

  return (
    <header className="header">
      <div className="brand">
        {isPlaying ? (
          <div className="brand-game-info">
            <span className="brand-game-label">Nice BINGO</span>
            <span className="brand-game-stats">
              👥 {realPlayers} player{realPlayers !== 1 ? 's' : ''} · 🃏 {cardsInPlay} card{cardsInPlay !== 1 ? 's' : ''}
            </span>
          </div>
        ) : (
          <>
            <span className="brand-royale">Nice BINGO</span>
          </>
        )}
      </div>

      <div className="chips">
        <div className="chip chip-room" title="Your room — each room has its own fixed bet">
          <span className="chip-icon">🚪</span>
          <select
            className="header-room-select"
            value={room}
            onChange={(e) => onRoomChange?.(Number(e.target.value))}
            title="Choose your room"
          >
            {(rooms || []).map((r) => (
              <option key={r} value={r}>Room {r}</option>
            ))}
          </select>
        </div>
        <div className="chip chip-credit" title="Your balance">
          <span className="chip-icon">💰</span>
          <span className="chip-num">{credit}</span>
          <span className="chip-label">ETB</span>
        </div>
        {/* the win pool is only shown once the round is running — it stays
            hidden during the preparation / card-selection window */}
        {pool != null && (
          <div className="chip chip-pool" title="This room's win pool">
            <span className="chip-icon">🏆</span>
            <span className="chip-num pool-pulse">{pool}</span>
            <span className="chip-label">ETB</span>
          </div>
        )}
        <button className="chip chip-btn" onClick={onToggleSettings} title="Settings & wallet">
          {currentPack.icon} ⚙️
        </button>
        {isAdmin && (
          <button className={`chip chip-btn ${showAdmin ? 'active' : ''}`} onClick={onToggleAdmin}>
            🛠
          </button>
        )}
        {isSuperAdmin && (
          <button className={`chip chip-btn ${showSuper ? 'active' : ''}`} onClick={onToggleSuper} title="Super admin">
            👑
          </button>
        )}
        <span className={`dot ${connected ? 'on' : ''}`} title={connected ? 'Live' : 'Offline'} />
      </div>
    </header>
  );
}
