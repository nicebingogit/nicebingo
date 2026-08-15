import { LETTERS } from '../bingo.js';

const RANGES = { B: [1, 15], I: [16, 30], N: [31, 45], G: [46, 60], O: [61, 75] };
export const COLORS = { B: '#ff5f7a', I: '#4be3a0', N: '#ffd54f', G: '#3ec8ff', O: '#d95cff' };

export default function CalledBoard({ called, currentCall }) {
  const set = new Set(called || []);
  // the most recently drawn ball is the LAST entry of the called list — prefer
  // it over current_call so the board always pops/highlights the newest ball
  // even if a poll snapshot carried a stale current_call
  const last = called?.[called.length - 1] || currentCall;

  return (
    <div className="board">
      {LETTERS.map((letter) => (
        <div className="board-row" key={letter}>
          <div
            className="board-letter"
            style={{ color: COLORS[letter], textShadow: `0 0 14px ${COLORS[letter]}66` }}
          >
            {letter}
          </div>
          <div className="board-balls">
            {Array.from({ length: 15 }, (_, i) => RANGES[letter][0] + i).map((n) => {
              const key = `${letter}-${n}`;
              const on = set.has(key);
              return (
                <div
                  key={key}
                  className={`ball ${on ? 'on' : ''} ${key === last ? 'last' : ''}`}
                  style={
                    on
                      ? {
                          borderColor: COLORS[letter],
                          color: COLORS[letter],
                          boxShadow: `0 0 8px ${COLORS[letter]}55`,
                        }
                      : {}
                  }
                >
                  {n}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
