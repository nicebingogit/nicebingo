import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api.js';
import { getTelegramUser, haptic } from './telegram.js';
import { playBall, playRoundStart, playWin, playLose, playCountdown, playClick, playDaub } from './sound.js';
import { checkPatterns, PATTERN_LABELS, cellKey, LETTERS } from './bingo.js';
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

// Auto-play threshold: players with more than this credit see the Auto-Play button
const AUTO_PLAY_CREDIT_THRESHOLD = 4;

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
  // AUTO-PLAY: when enabled, the client auto-daubs called numbers and
  // auto-claims BINGO — no manual tapping required. Card selection is manual.
  const [autoPlay, setAutoPlay] = useState(true);
  // Smooth countdown: interpolates between server polls so the number
  // ticks down every second without skipping
  const [smoothCountdown, setSmoothCountdown] = useState(0);
  const prepRef = useRef({ remaining: 0, timestamp: 0 });
  // the room (fixed bet) this player is currently in — picked via a listbox
  // in the card picker. Each room is its own game.
  const [room, setRoom] = useState(10);
  const prev = useRef({ count: -1, phase: null });
  const [spectating, setSpectating] = useState(null); // random other player's card
  const spectateUserIdRef = useRef(null); // pin to the same player across refreshes
  const spectateUserId = spectating?.spectate_user_id || spectateUserIdRef.current;

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
      let initialRoom = 10;
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

  // Sync smooth countdown with server value whenever it changes
  useEffect(() => {
    if (state?.phase !== 'preparation') return;
    const remaining = state.preparation_remaining || 0;
    prepRef.current = { remaining, timestamp: Date.now() };
    setSmoothCountdown(remaining);
  }, [state?.phase, state?.preparation_remaining]);

  // Tick countdown every second for smooth display (no skipped numbers)
  useEffect(() => {
    if (state?.phase !== 'preparation') return;
    const tick = setInterval(() => {
      const { remaining, timestamp } = prepRef.current;
      const elapsed = (Date.now() - timestamp) / 1000;
      const current = Math.max(0, Math.ceil(remaining - elapsed));
      setSmoothCountdown((prev) => {
        // Avoid unnecessary re-renders if value hasn't changed
        if (current === prev) return prev;
        return current;
      });
    }, 250); // tick 4x/sec for ultra-smooth display
    return () => clearInterval(tick);
  }, [state?.phase]);

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

  // ---- AUTO-PLAY: auto-daub all called numbers on the player's cards ----
  useEffect(() => {
    if (!autoPlay || state?.phase !== 'playing' || myCards.length === 0) return;
    // mark every called number on every card
    setMarked((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const c of myCards) {
        const cur = new Set(prev[c.card_id] || []);
        for (const key of state.called_numbers || []) {
          if (!cur.has(key)) {
            cur.add(key);
            changed = true;
          }
        }
        next[c.card_id] = cur;
      }
      return changed ? next : prev;
    });
  }, [autoPlay, state?.phase, state?.called_numbers, myCards]);

  // ---- AUTO-PLAY: auto-claim BINGO when a pattern is detected ----
  useEffect(() => {
    if (!autoPlay || state?.phase !== 'playing' || myCards.length === 0) return;
    if (myUser?.eliminated || state.winner) return;
    // check if any card has a winning pattern using current daubs
    for (const c of myCards) {
      const r = checkPatterns(c.numbers, marked[c.card_id] || new Set());
      if (r.patterns.length > 0) {
        // pattern found — auto-claim!
        haptic('medium');
        api.claimBingo(c.card_id, room)
          .then(() => refresh())
          .catch(() => refresh());
        break;
      }
    }
  }, [autoPlay, state?.phase, marked, myCards, myUser?.eliminated, state?.winner, room, refresh]);

  // ---- SPECTATOR MODE: fetch another player's card when no cards selected ----
  useEffect(() => {
    if (state?.phase !== 'playing' || myCards.length > 0) {
      setSpectating(null);
      spectateUserIdRef.current = null; // reset pinned player when entering own game
      return;
    }
    let cancelled = false;
    const fetchSpectate = async () => {
      try {
        // Pass the pinned user_id if we already picked one — stay on the same player
        const data = await api.spectate(room, spectateUserIdRef.current);
        if (!cancelled) {
          setSpectating(data);
          spectateUserIdRef.current = data.spectate_user_id || spectateUserIdRef.current;
        }
      } catch {
        if (!cancelled) setSpectating(null);
      }
    };
    fetchSpectate();
    // Re-fetch the SAME player's card every 10 seconds
    const t = setInterval(fetchSpectate, 10000);
    return () => { cancelled = true; clearInterval(t); };
  }, [state?.phase, myCards.length, room]);

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
        <div className="splash-brand">Nice BINGO</div>
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
        pool={state.phase === 'preparation' ? null : (state.win_pool ?? 0)}
        room={room}
        rooms={cfg.rooms || [10, 20, 30]}
        onRoomChange={changeRoom}
        isAdmin={myUser?.is_admin}
        isSuperAdmin={myUser?.is_super_admin}
        showAdmin={showAdmin}
        showSuper={showSuper}
        onToggleAdmin={() => { playClick(); setShowAdmin((s) => !s); setShowSuper(false); }}
        onToggleSuper={() => { playClick(); setShowSuper((s) => !s); setShowAdmin(false); }}
        onToggleSettings={() => setShowSettings((s) => !s)}
        connected={!error}
        phase={state?.phase}
        realPlayers={state?.real_players ?? 0}
        cardsInPlay={state?.cards_in_play ?? 0}
      />

      {/* AUTO-PLAY: floating button — always visible during preparation and play */}
      {(state?.phase === 'preparation' || state?.phase === 'playing') && (myUser?.credit ?? 0) >= AUTO_PLAY_CREDIT_THRESHOLD && (
        <button
          className={`auto-play-btn ${autoPlay ? 'active' : ''}`}
          onClick={() => { playClick(); haptic('medium'); setAutoPlay((a) => !a); }}
          title={autoPlay ? 'Disable auto-play' : 'Enable auto-play — daubs numbers and claims BINGO automatically!'}
        >
          {autoPlay ? '🤖 Auto ON' : '🤖 Auto Play'}
        </button>
      )}

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
                  {state.real_players + (state.bots_players || 0)} players · {state.cards_in_play} cards
                </div>
              </div>
              <div className="countdown">
                <div className="countdown-num">{smoothCountdown}</div>
                <div className="countdown-label">seconds</div>
              </div>
            </div>
            <div className="countdown-bar">
              <div
                className="countdown-fill"
                style={{ width: `${Math.min(100, (smoothCountdown / (cfg.preparation || 60)) * 100)}%` }}
              />
            </div>
          </div>
          <CardPicker
            selections={myCards}
            maxCards={cfg.max_cards || 3}
            room={room}
            credit={myUser?.credit ?? 0}
            onChanged={handleChanged}
            onError={showError}
            cardsInPlay={state.cards_in_play}
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
              <div className="cc-label">LAST NUMBER</div>
              <div className="cc-progress">
                {state.called_count} / {state.total_numbers} balls
              </div>
            </div>
          </div>

          <div className="game-layout">
            {/* Compact board + optional settings side-by-side on top */}
            <div className={`game-top-row${myCards.length === 3 ? ' compact-board' : ''}`}>
              <div className="game-board">
                <CalledBoard called={state.called_numbers} currentCall={state.current_call} />
              </div>
              {showSettings && myUser?.is_admin && (
                <div className="game-settings-side">
                  <div className="wallet-form-title" style={{ fontSize: 11, padding: '6px 8px', textAlign: 'center', color: 'var(--muted)' }}>
                    ⚙️ Settings (overlay)
                  </div>
                </div>
              )}
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
                  <div
                    className={`my-cards ${myCards.length === 1 ? 'single' : ''} card-count-${myCards.length}`}

                  >
                    {myWinning.map(({ card, patterns, cells }) => (
                      <BingoCard
                        key={card.card_id}
                        card={card}
                        markedSet={marked[card.card_id] || new Set()}
                        winCells={patterns.length ? cells : []}
                        size={myCards.length === 3 ? 'triple' : myCards.length === 2 ? 'medium' : 'small'}
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
                <div className="spectator-mode">
                  <div className="spectator-banner">
                    <div className="spectator-icon">👀</div>
                    <div className="spectator-info">
                      <div className="spectator-title">Spectating</div>
                      <div className="spectator-text">No cards this round — watching the game</div>
                    </div>
                  </div>
                  {spectating && spectating.numbers ? (
                    <div className="spectator-game">
                      <div className="spectator-player-name">Watching: {spectating.player_name}</div>
                      <BingoCard
                        card={{ card_id: spectating.card_id, numbers: spectating.numbers, bet_amount: spectating.bet_amount }}
                        markedSet={state.called_numbers ? new Set(state.called_numbers) : new Set()}
                        winCells={[]}
                        size="small"
                        interactive={false}
                        spectator={true}
                        calledNumbers={state.called_numbers || []}
                      />
                    </div>
                  ) : (
                    <div className="spectator-game">
                      <div className="spectator-loading">Looking for a player to watch...</div>
                    </div>
                  )}
                </div>
              )}

              {!myUser?.eliminated && myCards.length === 1 && (
                <div className="daub-hint">
                  Tap marked numbers on your card · Press BINGO to claim
                </div>
              )}

              {!myUser?.eliminated && myCards.length > 0 && (
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
