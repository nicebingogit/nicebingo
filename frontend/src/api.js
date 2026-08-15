import { getTelegramUser, initData } from './telegram.js';

const BASE = ''; // same origin: Flask serves both the app and the API

async function request(path, options = {}) {
  const user = getTelegramUser();
  const params = new URLSearchParams({ user_id: String(user.id) });
  if (user.username) params.set('username', user.username);
  if (initData) params.set('init_data', initData);
  for (const [k, v] of Object.entries(options.params || {})) {
    params.set(k, String(v));
  }
  let res;
  if (options.method === 'POST') {
    const body = { ...(options.body || {}), user_id: user.id };
    if (initData) body.init_data = initData;
    res = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } else {
    res = await fetch(`${BASE}${path}?${params.toString()}`);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || data.message || `HTTP ${res.status}`);
    // let the UI distinguish a false-BINGO elimination from a plain error
    if (data.eliminated) err.eliminated = true;
    throw err;
  }
  return data;
}

function adminRequest(path, options = {}) {
  const user = getTelegramUser();
  return request(path, {
    ...options,
    params: { ...(options.params || {}), admin_id: user.id },
    method: options.method || 'POST',
    body: { ...(options.body || {}), admin_id: user.id },
  });
}

// every request that touches a room carries the room (fixed bet) so the
// server knows WHICH room's game, cards and pool to answer with
function roomParams(room) {
  return room ? { room } : {};
}

export const api = {
  init: async (room) => {
    const d = await request('/api/init', { params: roomParams(room) });
    const { state, ...user } = d;
    return { user, state };
  },
  gameState: async (room) => {
    const d = await request('/api/game-state', { params: roomParams(room) });
    const { user, ...state } = d;
    return { user, state };
  },
  cards: async (room) => (await request('/api/cards', { params: roomParams(room) })).cards,
  // the bet is FIXED per room — there is no bet_amount anymore
  selectCard: (cardId, room) =>
    request('/api/select-card', { method: 'POST', body: { card_id: cardId, room } }),
  deselectCard: (cardId, room) =>
    request('/api/deselect-card', { method: 'POST', body: { card_id: cardId, room } }),
  quickPlay: (room) => request('/api/quick-play', { method: 'POST', body: { room } }),
  claimBingo: (cardId, room) =>
    request('/api/claim-bingo', { method: 'POST', body: { card_id: cardId, room } }),
  leaderboard: () => request('/api/leaderboard'),
  // the full name is collected by the BOT chat; the Mini App only adds the phone
  register: (phone, room) =>
    request('/api/register', { method: 'POST', body: { phone, ...roomParams(room) } }),
  // fields: { full_name?, phone? } — both are optional but at least one is sent
  updateProfile: (fields, room) =>
    request('/api/profile', { method: 'POST', body: { ...fields, ...roomParams(room) } }),
  deleteAccount: (room) =>
    request('/api/delete-account', { method: 'POST', body: { confirm: true, ...roomParams(room) } }),
  transactions: () => request('/api/transactions'),
  // extra: optional withdraw destination fields
  // (account_name / account_holder / account_number)
  createTransaction: (type, amount, txId, accountId, extra = {}) =>
    request('/api/transactions', {
      method: 'POST',
      body: { type, amount, tx_id: txId, payment_account_id: accountId, ...extra },
    }),
  admin: {
    stats: () => adminRequest('/api/admin/stats', { method: 'GET' }),
    bots: () => adminRequest('/api/admin/bots', { method: 'GET' }),
    forceStart: (room) => adminRequest('/api/admin/force-start', { body: roomParams(room) }),
    forceCall: (room) => adminRequest('/api/admin/force-call', { body: roomParams(room) }),
    reset: (room) => adminRequest('/api/admin/reset', { body: roomParams(room) }),
    addBots: (room) => adminRequest('/api/admin/bots/add', { body: roomParams(room) }),
    toggleBots: (enabled) => adminRequest('/api/admin/bots/toggle', { body: { enabled } }),
    credit: (target, amount) => adminRequest('/api/admin/credit', { body: { user_id: target, amount } }),
    users: () => adminRequest('/api/admin/users', { method: 'GET' }),
    deleteUser: (target) =>
      adminRequest('/api/admin/users/delete', { body: { user_id: target } }),
    transactions: () => adminRequest('/api/admin/transactions', { method: 'GET' }),
    reviewTransaction: (id, action) =>
      adminRequest('/api/admin/transactions/review', { body: { id, action } }),
    accounts: () => adminRequest('/api/admin/accounts', { method: 'GET' }),
    addAccount: (account) => adminRequest('/api/admin/accounts', { body: account }),
    updateAccount: (account) => adminRequest('/api/admin/accounts/update', { body: account }),
    deleteAccount: (id) => adminRequest('/api/admin/accounts/delete', { body: { id } }),
  },
};
