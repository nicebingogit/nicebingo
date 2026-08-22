import { PACKS, getPack } from '../sound.js';

const BRAND = { B: '#ff5f7a', I: '#4be3a0', N: '#ffd54f', G: '#3ec8ff', O: '#d95cff' };

export default function Header({ credit, pool, room, rooms, onRoomChange, isAdmin, isSuperAdmin, showAdmin, showSuper, onToggleAdmin, onToggleSuper, onToggleSettings, connected }) {
  const packIdx = PACKS.findIndex((p) => p.id === getPack());
  const currentPack = PACKS[packIdx] || PACKS[0];

  return (
    <header className="header">
      <div className="brand">
        {Object.entries(BRAND).map(([letter, color]) => (
          <span key={letter} className="brand-letter" style={{ color }}>{letter}</span>
        ))}
        <span className="brand-royale">NICE BINGO</span>
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
