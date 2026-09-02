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
    const body = { user_id: user.id, ...(options.body || {}) };
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

// Helper: try a request and return null if the endpoint doesn't exist yet
async function safeRequest(path, options = {}) {
  try {
    return await request(path, options);
  } catch (e) {
    // Return null silently if the endpoint is not implemented yet (404/405/500)
    return null;
  }
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
  spectate: (room, spectateUserId) => request('/api/spectate', { params: { ...roomParams(room), ...(spectateUserId ? { spectate_user_id: spectateUserId } : {}) } }),
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
  // wallet appeals — a deposit the admin never approved can be appealed; the
  // SUPER ADMIN resolves it
  appeals: () => request('/api/appeals'),
  fileAppeal: (transactionId, reason) =>
    request('/api/appeals', { method: 'POST', body: { transaction_id: transactionId, reason } }),
  // referral system
  referralLink: () => request('/api/referral/link'),
  referralCommissions: () => request('/api/referral/commissions'),
  referralLeaderboard: () => request('/api/referral/leaderboard'),
  referralRegister: (referrerId) =>
    request('/api/referral/register', { method: 'POST', body: { referrer_id: referrerId } }),
  userReferral: () => request('/api/user/referral'),
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
    providers: () => adminRequest('/api/admin/providers', { method: 'GET' }),
    addAccount: (account) => adminRequest('/api/admin/accounts', { body: account }),
    updateAccount: (account) => adminRequest('/api/admin/accounts/update', { body: account }),
    deleteAccount: (id) => adminRequest('/api/admin/accounts/delete', { body: { id } }),
  },
  // SUPER ADMIN — controls every account (admin or user), every log, admin
  // credits (selling credit to admins) and wallet appeals
  superAdmin: {
    users: () => superAdminRequest('/api/superadmin/users', { method: 'GET' }),
    credit: (target, amount, kind) =>
      superAdminRequest('/api/superadmin/credit', { body: { user_id: target, amount, target: kind } }),
    setAdmin: (target, isAdmin) =>
      superAdminRequest('/api/superadmin/admin', { body: { user_id: target, is_admin: isAdmin } }),
    editUser: (userId, fields) =>
      superAdminRequest('/api/superadmin/edit-user', { body: { user_id: userId, ...fields } }),
    transactions: () => superAdminRequest('/api/superadmin/transactions', { method: 'GET' }),
    reviewTransaction: (id, action) =>
      superAdminRequest('/api/superadmin/transactions/review', { body: { id, action } }),
    accounts: () => superAdminRequest('/api/superadmin/accounts', { method: 'GET' }),
    updateAccount: (account) => superAdminRequest('/api/superadmin/accounts/update', { body: account }),
    deleteAccount: (id) => superAdminRequest('/api/superadmin/accounts/delete', { body: { id } }),
    activityLog: () => superAdminRequest('/api/superadmin/activity-log', { method: 'GET' }),
    appeals: () => superAdminRequest('/api/superadmin/appeals', { method: 'GET' }),
    resolveAppeal: (id, action, resolution) =>
      superAdminRequest('/api/superadmin/appeals/resolve', { body: { id, action, resolution } }),
    // game controls
    pauseGame: (room) => superAdminRequest('/api/superadmin/game/pause', { body: roomParams(room) }),
    resumeGame: (room) => superAdminRequest('/api/superadmin/game/resume', { body: roomParams(room) }),
    // announcements
    announcements: () => safeRequest('/api/announcements'),
    postAnnouncement: (text) => superAdminRequest('/api/superadmin/announcements', { body: { text } }),
    updateAnnouncement: (id, text) => superAdminRequest('/api/superadmin/announcements/update', { body: { id, text } }),
    deleteAnnouncement: (id) => superAdminRequest('/api/superadmin/announcements/delete', { body: { id } }),
    // gameplay history (game results log)
    gameplayHistory: () => superAdminRequest('/api/superadmin/gameplay-history', { method: 'GET' }),

    stopGame: (room) => superAdminRequest('/api/superadmin/game/stop', { body: roomParams(room) }),
    startGame: (room) => superAdminRequest('/api/superadmin/game/start', { body: roomParams(room) }),
    addBots: (room) => superAdminRequest('/api/superadmin/game/add-bots', { body: roomParams(room) }),
    setBotsDifficulty: (difficulty) => superAdminRequest('/api/superadmin/game/bots-difficulty', { body: { difficulty } }),
    toggleBots: (enabled) => superAdminRequest('/api/superadmin/game/bots-toggle', { body: { enabled } }),
  },
};

// super-admin requests are guarded by admin_id == SUPER_ADMIN_ID server-side
function superAdminRequest(path, options = {}) {
  return adminRequest(path, options);
}
