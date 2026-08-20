import { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import { playClick } from '../sound.js';

export default function CardPicker({ selections, maxCards, rooms, room, onRoomChange, credit, onChanged, onError }) {
  const [cards, setCards] = useState(null);
  const [busy, setBusy] = useState(null);
  const [quickBusy, setQuickBusy] = useState(false);

  useEffect(() => {
    setCards(null);
    api.cards(room).then(setCards).catch((e) => onError?.(e.message));
  }, [room, onError]);

  const selectedIds = useMemo(() => new Set(selections.map((s) => s.card_id)), [selections]);
  const takenByOthers = useMemo(() => {
    const m = new Map((cards || []).map((c) => [c.id, c.taken_by_me ? 'mine' : c.taken ? 'taken' : 'free']));
    return m;
  }, [cards]);
  const full = selections.length >= maxCards;

  const toggle = async (card) => {
    playClick();
    setBusy(card.id);
    try {
      if (selectedIds.has(card.id)) {
        await api.deselectCard(card.id, room);
      } else if (takenByOthers.get(card.id) !== 'taken') {
        await api.selectCard(card.id, room);
      }
      await onChanged();
    } catch (e) {
      onError?.(e.message);
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  const quickPlay = async () => {
    playClick();
    setQuickBusy(true);
    try {
      await api.quickPlay(room);
      await onChanged();
    } catch (e) {
      onError?.(e.message);
    } finally {
      setQuickBusy(false);
    }
  };

  if (!cards) return <div className="panel loading">Loading cards…</div>;

  return (
    <div className="panel">
      <div className="picker-bar">
        <div className="picker-title">
          🃏 Pick your cards <span className="muted">({selections.length}/{maxCards})</span>
        </div>
        {/* the bet amount is gone — each room has a FIXED bet per card; the
            listbox picks which room (30 / 50 / 100) you play in */}
        <label className="bet-box">
          <span className="muted">Room</span>
          <select
            className="room-select"
            value={room}
            onChange={(e) => onRoomChange?.(Number(e.target.value))}
            title="Choose your room — the bet per card is fixed per room"
          >
            {rooms.map((r) => (
              <option key={r} value={r}>
                Room by {r} · {r} ETB/card
              </option>
            ))}
          </select>
        </label>
        <button className="btn btn-ghost" onClick={quickPlay} disabled={quickBusy || full}>
          {quickBusy ? '…' : '⚡ Quick Play'}
        </button>
      </div>

      {selections.length > 0 && (
        <div className="my-picks">
          {selections.map((s) => (
            <button key={s.card_id} className="pick-chip" onClick={() => toggle({ id: s.card_id })}>
              #{s.card_id} · {s.bet_amount} ETB <span className="pick-x">✕</span>
            </button>
          ))}
        </div>
      )}

      <div className="card-grid-picker">
        {cards.map((card) => {
          const status = takenByOthers.get(card.id);
          const mine = status === 'mine';
          const taken = status === 'taken';
          const disabled = taken || (full && !mine);
          return (
            <button
              key={card.id}
              className={`pick-tile ${mine ? 'mine' : ''} ${taken ? 'taken' : ''}`}
              disabled={disabled || busy === card.id}
              onClick={() => toggle(card)}
              title={taken ? 'Taken' : mine ? 'Your card' : `Card #${card.id}`}
            >
              <span className="pick-tile-id">#{card.id}</span>
              {mine ? (
                <span className="pick-tile-badge">✓</span>
              ) : taken ? (
                <span className="pick-tile-badge lock">🔒</span>
              ) : null}
            </button>
          );
        })}
      </div>

    </div>
  );
}
