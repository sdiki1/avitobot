const BACKEND_URL = (process.env.BACKEND_URL || 'http://localhost:8001').replace(/\/$/, '');
const ADMIN_API_TOKEN = process.env.ADMIN_API_TOKEN || 'change_me_admin_token';

async function request(path, options = {}) {
  const url = new URL(`${BACKEND_URL}/api/v1/admin${path}`);
  if (options.body) {
    url.searchParams.set('__body', String(options.body));
  }
  const response = await fetch(url, {
    headers: {
      'X-Admin-Token': ADMIN_API_TOKEN,
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`API ${response.status}: ${body}`);
  }

  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function withPayload(payload) {
  return { body: JSON.stringify(payload) };
}

exports.getStats = () => request('/stats');
exports.getPlans = () => request('/plans');
exports.createPlan = (payload) => request('/plans/create', withPayload(payload));
exports.updatePlan = (id, payload) => request(`/plans/${id}/update`, withPayload(payload));
exports.deletePlan = (id) => request(`/plans/${id}/delete`);

exports.getPromoCodes = () => request('/promo-codes');
exports.getPromoCodeStats = (id, { dateFrom, dateTo } = {}) => {
  const params = new URLSearchParams();
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  const query = params.toString();
  return request(`/promo-codes/${id}/stats${query ? `?${query}` : ''}`);
};
exports.createPromoCode = (payload) => request('/promo-codes/create', withPayload(payload));
exports.updatePromoCode = (id, payload) => request(`/promo-codes/${id}/update`, withPayload(payload));
exports.deletePromoCode = (id) => request(`/promo-codes/${id}/delete`);

exports.getProxies = () => request('/proxies');
exports.createProxy = (payload) => request('/proxies/create', withPayload(payload));
exports.updateProxy = (id, payload) => request(`/proxies/${id}/update`, withPayload(payload));
exports.deleteProxy = (id) => request(`/proxies/${id}/delete`);

exports.getUsers = () => request('/users');
exports.addAdminUser = (payload) => request('/users/admins', withPayload(payload));
exports.updateUserAdmin = (id, payload) => request(`/users/${id}/admin`, withPayload(payload));
exports.getMonitorings = () => request('/monitorings');
exports.updateMonitoring = (id, payload) => request(`/monitorings/${id}/update`, withPayload(payload));
exports.getTrialSettings = () => request('/trial-settings');
exports.updateTrialSettings = (payload) => request('/trial-settings/update', withPayload(payload));
exports.getReferralSettings = () => request('/referral-settings');
exports.updateReferralSettings = (payload) => request('/referral-settings/update', withPayload(payload));
exports.getMiniappContent = () => request('/miniapp-content');
exports.updateMiniappContent = (payload) => request('/miniapp-content/update', withPayload(payload));

exports.getBots = () => request('/bots');
exports.createBot = (payload) => request('/bots/create', withPayload(payload));
exports.updateBot = (id, payload) => request(`/bots/${id}/update`, withPayload(payload));
exports.deleteBot = (id) => request(`/bots/${id}/delete`);

exports.getPayments = () => request('/payments');
exports.createPayment = (payload) => request('/payments/create', withPayload(payload));
exports.getPaymentSettings = () => request('/payment-settings');
exports.updatePaymentSettings = (payload) => request('/payment-settings/update', withPayload(payload));
exports.activateSubscription = (payload) =>
  request('/subscriptions/activate', withPayload(payload));
exports.grantBonusDaysAll = (payload) =>
  request('/subscriptions/grant-days-all', withPayload(payload));
exports.grantBonusDaysUser = (payload) =>
  request('/subscriptions/grant-days-user', withPayload(payload));
exports.broadcast = (payload) =>
  request('/broadcast', withPayload(payload));
