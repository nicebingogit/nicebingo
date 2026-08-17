import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api.js';
import { getTelegramUser, haptic } from './telegram.js';
import { playBall, playRoundStart, playWin, playLose, playCountdown, playClick, playDaub } from './sound.js';
import { checkPatterns, PATTERN_LABELS, cellKey } from './bingo.js';
import Header from './components/Header.jsx';
import CalledBoard, { COLORS as BALL_COLORS } from './components/CalledBoard.jsx';
import BingoCard from './components/BingoCard.jsx';
import CardPicker from './components/CardPicker.jsx';
import WinnerModal from './components/WinnerModal.jsx';
import AdminPanel from './components/AdminPanel.jsx';
import SuperAdminPanel from './components/SuperAdminPanel.jsx';
import Registration from './components/Registration.jsx';
import Settings from './components/Settings.jsx';

const POLL_MS_PLAY = 2000;   // live rounds feel smooth at 2s
const POLL_MS_IDLE = 4000;   // preparation / ended: fewer requests = lighter server

// the last known session is cached locally so reopening the app paints
// INSTANTLY (stale-while-revalidate) instead of staring at the splash screen
const SESSION_CACHE_KEY = 'bingo_session_v1';
const ROOM_CACHE_KEY = 'bingo_room_v1';

function cacheSession(s) {
  try { sessionStorage.setItem(SESSION_CACHE_KEY, JSON.stringify(s)); } catch { /* ignore */ }
}

export default function App() {
  const user = useMemo(() => getTelegramUser(), []);
  const [session, setSession] = useState(null); // { user, state }
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAdmin, setShowAdmin] = useState(false);
  const [showSuper, setShowSuper] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [toast, setToast] = useState('');
  const [modalClosed, setModalClosed] = useState(false);
  const [eliminatedNotice, setEliminatedNotice] = useState(false);
  // MANUAL play — the player daubs the called numbers on their own card (paper
  // bingo style). These marks are purely client-side; the server verifies the
  // claim against the real called numbers when BINGO is pressed.
  // shape: { card_id: Set<"B-7", "N-44", ...> }
  const [marked, setMarked] = useState({});
  // the room (fixed bet) this player is currently in — picked via a listbox
  // in the card picker. Each room is its own game.
  const [room, setRoom] = useState(30);
  const prev = useRef({ count: -1, phase: null });

  const state = session?.state;
  const myUser = session?.user;
  const myCards = myUser?.selections || [];

  const showError = useCallback((msg) => {
    setToast(msg);
    setTimeout(() => setToast(''), 4000);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await api.gameState(room);
      setSession(data);
      cacheSession(data);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [room]);

  // bootstrap: paint the cached state instantly (if any), then refresh live
  useEffect(() => {
    (async () => {
      let initialRoom = 30;
      try {
        const raw = sessionStorage.getItem(SESSION_CACHE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (parsed?.state && parsed?.user) {
            setSession(parsed);
            // seed the sound tracker from the cached state so reopening in the
            // middle of a round doesn't replay sounds
            prev.current = {
              count: parsed.state.called_count ?? -1,
              phase: parsed.state.phase,
            };
            setLoading(false);
          }
        }
        const savedRoom = parseInt(sessionStorage.getItem(ROOM_CACHE_KEY), 10);
        if (savedRoom) initialRoom = savedRoom;
      } catch { /* ignore */ }
      try {
        const data = await api.init(initialRoom);
        // honour the server's default room (ROOM_BETS may be overridden in .env)
        const def = data.state?.config?.room_default;
        if (def && def !== initialRoom) {
          initialRoom = def;
          setRoom(def);
          const d2 = await api.gameState(def);
          cacheSession(d2);
          setSession(d2);
        } else {
          setRoom(initialRoom);
          cacheSession(data);
          setSession(data);
        }
        setError(null);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
    // the room only needs to be re-fetched when the player switches rooms
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // switching rooms in the picker reloads that room's game
  const changeRoom = useCallback((r) => {
    playClick();
    setModalClosed(false);
    setEliminatedNotice(false);
    setMarked({}); // a different room = a different game
    setRoom(r);
    try { sessionStorage.setItem(ROOM_CACHE_KEY, String(r)); } catch { /* ignore */ }
    api.gameState(r)
      .then((s) => { cacheSession(s); setSession(s); })
      .catch((e) => showError(e.message));
  }, [showError]);

  // polling loop — faster while numbers are being called, slower otherwise so
  // hundreds of players don't hammer the server during preparation
  useEffect(() => {
    const interval = state?.phase === 'playing' ? POLL_MS_PLAY : POLL_MS_IDLE;
    const t = setInterval(refresh, interval);
    return () => clearInterval(t);
  }, [refresh, state?.phase]);

  // sound triggers on state changes
  useEffect(() => {
    if (!state) return;
    const p = prev.current;
    if (p.count >= 0 && state.called_count > p.count && state.current_call) {
      playBall(state.current_call);
      haptic('light');
    }
    if (state.phase !== p.phase) {
      if (state.phase === 'playing') {
        playRoundStart();
        haptic('medium');
      }
      if (state.phase === 'ended' && state.winner) {
        if (state.winner.user_id === user.id) {
          playWin();
          haptic('success');
        } else {
          playLose();
          haptic('warning');
        }
        setModalClosed(false);
      }
      if (state.phase === 'preparation' && p.phase === 'ended') playCountdown();
      // a fresh round clears any false-BINGO elimination state
      if (state.phase === 'preparation') setEliminatedNotice(false);
    }
    prev.current = { count: state.called_count, phase: state.phase };
  }, [state, user.id]);

  // toggle a daub on one of the player's cards. If the SAME number exists on
  // the player's other cards it is daubed there automatically too — tapping a
  // number once marks it everywhere it appears (no need to repeat yourself).
  const toggleCell = useCallback((cardId, letter, value) => {
    const key = cellKey(letter, value);
    setMarked((prev) => {
      const next = { ...prev };
      const source = new Set(prev[cardId] || []);
      const mark = !source.has(key);
      for (const c of myCards) {
        if (!(c.numbers?.[letter] || []).includes(value)) continue;
        const cur = new Set(prev[c.card_id] || []);
        if (mark) cur.add(key);
        else cur.delete(key);
        next[c.card_id] = cur;
      }
      return next;
    });
  }, [myCards]);

  // multi-card shortcut: daub ONE called number on ALL of the player's cards
  // at once (tap a ball in the strip above the cards). Tapping again removes
  // it everywhere.
  const toggleCellAll = useCallback((key) => {
    setMarked((prev) => {
      const next = { ...prev };
      const allMarked = myCards.every((c) => (prev[c.card_id] || new Set()).has(key));
      for (const c of myCards) {
        const cur = new Set(prev[c.card_id] || []);
        if (allMarked) cur.delete(key);
        else cur.add(key);
        next[c.card_id] = cur;
      }
      return next;
    });
  }, [myCards]);

  // a fresh round starts with a blank card again
  useEffect(() => {
    if (state?.phase === 'preparation') setMarked({});
  }, [state?.phase]);

  // client-side pattern highlighting runs over the player's OWN daubs and is
  // VISUAL ONLY — the button stays active for every player with cards so the
  // SERVER can judge the claim against the real called numbers
  const myWinning = useMemo(
    () =>
      myCards.map((c) => {
        const r = checkPatterns(c.numbers, marked[c.card_id] || new Set());
        return { card: c, ...r };
      }),
    [myCards, marked],
  );
  const hasLocalPattern = myWinning.some((w) => w.patterns.length > 0);
  const claimable =
    state?.phase === 'playing' &&
    myCards.length > 0 &&
    !myUser?.eliminated &&
    !state.winner;

  const claim = async () => {
    playClick();
    haptic('medium');
    try {
      await api.claimBingo(myCards[0]?.card_id, room);
      await refresh();
    } catch (e) {
      if (e.eliminated) {
        // false BINGO — the server eliminated us from this round
        setEliminatedNotice(true);
      } else {
        showError(e.message);
      }
      await refresh();
    }
  };

  const handleChanged = async () => {
    try { await refresh(); } catch { /* ignore */ }
  };

  const handleRegistered = async () => {
    setShowSettings(false);
    try { await refresh(); } catch { /* ignore */ }
  };

  if (loading) {
    return (
      <div className="splash">
        <div className="splash-brand">B·I·N·G·O</div>
        <div className="splash-sub">Connecting to the arena…</div>
        <div className="spinner" />
      </div>
    );
  }

  if (!state && error) {
    return (
      <div className="splash">
        <div className="splash-brand">⚠️</div>
        <div className="splash-sub">{error}</div>
        <button className="btn btn-primary" onClick={refresh}>Retry</button>
      </div>
    );
  }

  const cfg = state.config || {};
  const endedWithWinner = state.phase === 'ended' && state.winner && !modalClosed;

  // First-time onboarding: the account exists but is not fully registered.
  // The bot collects the full name in the chat; the Mini App only adds the
  // phone (Registration handles the 'go to the bot chat first' gate).
  if (myUser && myUser.is_registered === false) {
    return (
      <div className="app">
        <Registration user={myUser} onDone={handleRegistered} onError={showError} />
        {toast && <div className="toast">{toast}</div>}
      </div>
    );
  }

  return (
    <div className="app">
      <Header
        credit={myUser?.credit ?? 0}
        // the win pool stays hidden until the round actually starts
        pool={state.phase === 'preparation' ? null : (state.win_pool ?? 0)}
        room={room}
        isAdmin={myUser?.is_admin}
        isSuperAdmin={myUser?.is_super_admin}
        showAdmin={showAdmin}
        showSuper={showSuper}
        onToggleAdmin={() => { playClick(); setShowAdmin((s) => !s); setShowSuper(false); }}
        onToggleSuper={() => { playClick(); setShowSuper((s) => !s); setShowAdmin(false); }}
        onToggleSettings={() => setShowSettings((s) => !s)}
        connected={!error}
      />

      {showAdmin && myUser?.is_admin && (
        <AdminPanel room={room} onError={showError} onChanged={handleChanged} />
      )}

      {showSuper && myUser?.is_super_admin && (
        <SuperAdminPanel onError={showError} />
      )}

      {showSettings && (
        <Settings
          user={myUser}
          settings={state.settings}
          config={cfg}
          onChanged={handleChanged}
          onError={showError}
          onClose={() => setShowSettings(false)}
        />
      )}

      {state.phase === 'preparation' && (
        <section className="phase-prep">
          <div className="hero-card">
            <div className="hero-top">
              <div>
                <div className="hero-title">Next round · Preparation</div>
                {/* the winning amount stays hidden until the round starts */}
                <div className="hero-sub">
                  {state.real_players} players · {state.bots_players || 0} bots · {state.cards_in_play} cards
                </div>
              </div>
              <div className="countdown" key={Math.floor(state.preparation_remaining / 1)}>
                <div className="countdown-num">{state.preparation_remaining}</div>
                <div className="countdown-label">seconds</div>
              </div>
            </div>
            <div className="countdown-bar">
              <div
                className="countdown-fill"
                style={{ width: `${Math.min(100, (state.preparation_remaining / (cfg.preparation || 60)) * 100)}%` }}
              />
            </div>
          </div>
          <CardPicker
            selections={myCards}
            maxCards={cfg.max_cards || 3}
            rooms={cfg.rooms || [30, 50, 100]}
            room={room}
            onRoomChange={changeRoom}
            credit={myUser?.credit ?? 0}
            onChanged={handleChanged}
            onError={showError}
          />
        </section>
      )}

      {state.phase === 'playing' && (
        <section className="phase-play">
          <div className="current-call">
            <div className="cc-ball" key={state.current_call}>
              {state.current_call || '–'}
            </div>
            <div className="cc-info">
              {/* the room is already shown in the header chip — no need to
                  repeat it here; the saved space goes to bigger cards */}
              <div className="cc-label">LAST NUMBER</div>
              <div className="cc-progress">
                {state.called_count} / {state.total_numbers} balls
              </div>
            </div>
          </div>            <div className="game-layout">
              {/* horizontal calling board on TOP, the user's cards at the bottom */}
              <div className="game-board">
                <CalledBoard called={state.called_numbers} currentCall={state.current_call} />
              </div>
              <div className="game-left">
                {myUser?.eliminated && (
                  <div className="eliminated-banner">
                    <div className="eliminated-title">❌ FALSE BINGO!</div>
                    <p className="muted">
                      Your card did not have a valid winning pattern. You have
                      been eliminated from this round and your bet is lost —
                      no refund. Your cards stay visible below, but you can't
                      daub or claim again this round. 🍀
                    </p>
                  </div>
                )}
                {myCards.length > 0 ? (
                  <>
                    {/* multi-card: a compact list of called numbers right above
                        the cards, so the player can daub across ALL cards
                        without looking up at the big board */}
                    {!myUser?.eliminated && myCards.length > 1 && state.called_numbers.length > 0 && (
                      <div className="called-strip">
                        <span className="called-strip-label">📣 Called</span>
                        <div className="called-strip-balls">
                          {state.called_numbers.map((key) => {
                            const [letter, num] = key.split('-');
                            const color = BALL_COLORS[letter] || 'var(--gold)';
                            const allMarked = myCards.every((c) => (marked[c.card_id] || new Set()).has(key));
                            return (
                              <button
                                key={key}
                                type="button"
                                className={`strip-ball ${allMarked ? 'daubed' : ''}`}
                                style={{ '--ball-color': color }}
                                onClick={() => { haptic('light'); playDaub(); toggleCellAll(key); }}
                                title="Tap to mark this number on all your cards"
                              >
                                {letter}{num}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}
                    {/* 3 cards wrap 2+1 (bigger touch targets) — never more
                        than two cards per row, and everything stays on one
                        screen (the play column is height-capped) */}
                    <div
                      className={`my-cards ${myCards.length === 1 ? 'single' : ''}`}
                      style={{ gridTemplateColumns: `repeat(${Math.min(myCards.length, 2)}, 1fr)` }}
                    >
                      {myWinning.map(({ card, patterns, cells }) => (
                        <BingoCard
                          key={card.card_id}
                          card={card}
                          markedSet={marked[card.card_id] || new Set()}
                          winCells={patterns.length ? cells : []}
                          // compact by default (a full-width single card would
                          // push the BINGO button below the screen edge); with
                          // 3 cards they get a touch bigger for readability —
                          // the layout is height-capped so nothing overflows
                          size={myCards.length === 3 ? 'triple' : 'small'}
                          interactive={!myUser?.eliminated}
                          onToggleCell={(letter, value) => {
                            haptic('light');
                            playDaub();
                            toggleCell(card.card_id, letter, value);
                          }}
                        />
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="no-cards">You're not in this round — wait for the next one!</div>
                )}

                {!myUser?.eliminated && myCards.length === 1 && (
                  <div className="daub-hint">
                    Numbers are called on the board above — tap each one on your
                    card to mark it. Press BINGO when you believe you've won!
                  </div>
                )}

                {!myUser?.eliminated && (
                  <button
                    className={`btn bingo-btn ${claimable ? 'claimable' : ''} ${claimable && hasLocalPattern ? 'ready' : ''}`}
                    onClick={claim}
                    disabled={!claimable}
                    title="Tap the called numbers on your card, then press when you believe you have a winning pattern — the server verifies it!"
                  >
                    {claimable && hasLocalPattern ? '🔔 BINGO! Press now!' : claimable ? '🔔 BINGO' : '🔕 BINGO'}
                  </button>
                )}
                {hasLocalPattern && !myUser?.eliminated && (
                  <div className="claim-hint">
                    {PATTERN_LABELS[myWinning.find((w) => w.patterns.length > 0).patterns[0]]} complete — press BINGO!
                  </div>
                )}
              </div>
            </div>
        </section>
      )}

      {state.phase === 'ended' && !endedWithWinner && (
        <section className="phase-ended">
          <div className="ended-card">
            <div className="ended-title">Round finished · Room by {room}</div>
            {state.winner ? (
              <p className="ended-sub">
                🏆 <b>{state.winner.name}</b> won <b className="gold">{state.winner.prize} ETB</b>{' '}
                ({PATTERN_LABELS[state.winner.pattern] || state.winner.pattern})
              </p>
            ) : (
              <p className="ended-sub">All 75 balls were called — no winner this round.</p>
            )}
            <p className="muted">Next round starts in a few seconds…</p>
          </div>
          <CalledBoard called={state.called_numbers} currentCall={state.current_call} />
        </section>
      )}

      {endedWithWinner && (
        <WinnerModal winner={state.winner} myId={user.id} onClose={() => setModalClosed(true)} />
      )}

      {eliminatedNotice && (
        <EliminatedModal onClose={() => { playClick(); setEliminatedNotice(false); }} />
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

// False-BINGO elimination modal — vibrates with an error nudge on open
function EliminatedModal({ onClose }) {
  useEffect(() => { haptic('error'); }, []);
  return (
    <div className="modal-overlay">
          <div className="modal-card lost">
            <div className="trophy">❌</div>
            <h2>FALSE BINGO!</h2>
            <p className="muted">
              Your card did not have a valid winning pattern. You have been
              eliminated from this round and your bet has been lost — no
              refund. Wait for the next round!
            </p>
            <button className="btn btn-primary" onClick={onClose}>
              OK
            </button>
          </div>
        </div>
  );
}
