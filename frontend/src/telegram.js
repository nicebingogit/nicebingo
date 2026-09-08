// Telegram Web App SDK wrapper.
// Identity resolution (always yields a usable user_id, so the Mini App never
// shows "Missing or invalid user_id"):
//   1. Inside Telegram        -> real id from initDataUnsafe (server verifies
//                                the initData signature and trusts this id).
//   2. ?user_id= in the URL   -> browser testing / deep links.
//   3. Otherwise              -> a persistent random guest id (localStorage),
//                                so opening the app in any plain browser works
//                                too (every device gets its own identity).
const tg = window.Telegram?.WebApp || null;
const GUEST_KEY = 'bingo_guest_id';

function guestId() {
  try {
    let id = parseInt(localStorage.getItem(GUEST_KEY) || '', 10);
    if (!id || id <= 0) {
      id = Math.floor(1e9 + Math.random() * 9e8); // 10-digit positive int
      localStorage.setItem(GUEST_KEY, String(id));
    }
    return id;
  } catch {
    return Math.floor(1e9 + Math.random() * 9e8);
  }
}

export function getTelegramUser() {
  const raw = tg?.initDataUnsafe?.user;
  const params = new URLSearchParams(window.location.search);
  const queryId = parseInt(params.get('user_id') || '0', 10);
  const id = raw?.id ?? (queryId > 0 ? queryId : guestId());
  const username = raw?.username
    || raw?.first_name
    || params.get('username')
    || (id ? `Player_${id}` : 'Guest');
  return { id, username, isTelegram: !!tg };
}

export function initTelegram() {
  if (!tg) return;
  try {
    tg.ready();
    tg.expand();
    tg.setHeaderColor?.('#0b0f24');
    tg.setBackgroundColor?.('#0b0f24');
    tg.disableVerticalSwipes?.();
  } catch {
    /* older SDK — ignore */
  }
}

export const isTelegram = !!tg;
export const initData = tg?.initData || '';
export const themeParams = tg?.themeParams || {};

// Ask Telegram to show the native "Share phone number" dialog.
// Resolves with the phone number string, or null when the user cancels or
// the client doesn't support requestContact (old clients / desktop web / a
// plain browser). The UI falls back to a manual input in that case, so the
// registration flow works on EVERY device — never a dead end.
export function requestPhoneContact() {
  return new Promise((resolve) => {
    if (!tg || typeof tg.requestContact !== 'function') {
      resolve(null);
      return;
    }
    try {
      // handle BOTH callback signatures across clients:
      //   modern:  callback({status, responseUnsafe, response})
      //   legacy:  callback(status, response)   (status is a string)
      tg.requestContact((first, second) => {
        try {
          const status = typeof first === 'string' ? first : first?.status;
          const payload = (typeof first === 'string' ? second : first) || {};
          if (status === 'sent') {
            const contact =
              payload.responseUnsafe?.contact ||
              payload.response?.contact ||
              {};
            const phone = contact.phone_number || contact.phoneNumber || '';
            resolve(String(phone).trim() || null);
          } else {
            resolve(null); // 'cancelled' / 'app_chat' / callback-less client
          }
        } catch {
          resolve(null);
        }
      });
    } catch {
      resolve(null);
    }
  });
}

export function getTelegramName() {
  const raw = tg?.initDataUnsafe?.user;
  if (!raw) return '';
  return [raw.first_name, raw.last_name].filter(Boolean).join(' ').trim();
}

// Phone vibration on critical moments, via the Telegram HapticFeedback API
// (works in the native Mini App). Falls back to navigator.vibrate in a plain
// browser. Types:
//   'light' | 'medium' | 'heavy'  -> impactOccurred
//   'success' | 'warning' | 'error' -> notificationOccurred
const VIBRATE_PATTERN = {
  light: 15,
  medium: [20, 20, 20],
  heavy: [40, 30, 40],
  success: [30, 40, 60],
  warning: [50, 30, 50],
  error: [70, 40, 70],
};

export function haptic(type = 'light') {
  try {
    const h = tg?.HapticFeedback;
    if (h) {
      if (type === 'success' || type === 'warning' || type === 'error') {
        h.notificationOccurred?.(type);
      } else {
        h.impactOccurred?.(type === 'heavy' ? 'heavy' : type === 'medium' ? 'medium' : 'light');
      }
      return;
    }
    if (navigator.vibrate) {
      const pattern = VIBRATE_PATTERN[type] || 15;
      navigator.vibrate(Array.isArray(pattern) ? pattern : [pattern]);
    }
  } catch {
    /* haptics unsupported — ignore */
  }
}
