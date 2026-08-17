import { useEffect, useState } from 'react';
import { PACKS, getPack, setPack } from '../sound.js';

const BRAND = { B: '#ff5f7a', I: '#4be3a0', N: '#ffd54f', G: '#3ec8ff', O: '#d95cff' };

export default function Header({ credit, pool, room, isAdmin, isSuperAdmin, showAdmin, showSuper, onToggleAdmin, onToggleSuper, onToggleSettings, connected }) {
  const [packIdx, setPackIdx] = useState(() => PACKS.findIndex((p) => p.id === getPack()));

  const cyclePack = () => {
    const next = (packIdx + 1) % PACKS.length;
    setPackIdx(next);
    setPack(PACKS[next].id);
  };

  return (
    <header className="header">
      <div className="brand">
        {Object.entries(BRAND).map(([letter, color]) => (
          <span key={letter} className="brand-letter" style={{ color }}>{letter}</span>
        ))}
        <span className="brand-royale">ROYALE</span>
      </div>

      <div className="chips">
        <div className="chip chip-room" title="Your room — each room has its own fixed bet">
          <span className="chip-icon">🚪</span>
          <span className="chip-num">{room}</span>
          <span className="chip-label">ETB ROOM</span>
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
        <button className="chip chip-btn" onClick={cyclePack} title="Sound pack">
          {PACKS[packIdx].label}
        </button>
        <button className="chip chip-btn" onClick={onToggleSettings} title="Settings & wallet">
          ⚙️
        </button>
        {isAdmin && (
          <button className={`chip chip-btn ${showAdmin ? 'active' : ''}`} onClick={onToggleAdmin}>
            🛠 Admin
          </button>
        )}
        {isSuperAdmin && (
          <button className={`chip chip-btn ${showSuper ? 'active' : ''}`} onClick={onToggleSuper} title="Super admin — control every account, log and credit">
            👑 Super
          </button>
        )}
        <span className={`dot ${connected ? 'on' : ''}`} title={connected ? 'Live' : 'Offline'} />
      </div>
    </header>
  );
}
