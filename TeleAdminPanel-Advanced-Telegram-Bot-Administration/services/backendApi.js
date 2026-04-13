const BACKEND_URL = (process.env.BACKEND_URL || 'http://localhost:8001').replace(/\/$/, '');
const ADMIN_API_TOKEN = process.env.ADMIN_API_TOKEN || 'change_me_admin_token';

async function request(path, options = {}) {
  const url = `${BACKEND_URL}/api/v1/admin${path}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
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

exports.getStats = () => request('/stats');
exports.getPlans = () => request('/plans');
exports.createPlan = (payload) => request('/plans', { method: 'POST', body: JSON.stringify(payload) });
exports.updatePlan = (id, payload) => request(`/plans/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
exports.deletePlan = (id) => request(`/plans/${id}`, { method: 'DELETE' });

exports.getProxies = () => request('/proxies');
exports.createProxy = (payload) => request('/proxies', { method: 'POST', body: JSON.stringify(payload) });
exports.updateProxy = (id, payload) => request(`/proxies/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
exports.deleteProxy = (id) => request(`/proxies/${id}`, { method: 'DELETE' });

exports.getUsers = () => request('/users');
exports.getMonitorings = () => request('/monitorings');
exports.getTrialSettings = () => request('/trial-settings');
exports.updateTrialSettings = (payload) => request('/trial-settings', { method: 'PUT', body: JSON.stringify(payload) });
exports.getMiniappContent = () => request('/miniapp-content');
exports.updateMiniappContent = (payload) => request('/miniapp-content', { method: 'PUT', body: JSON.stringify(payload) });

exports.getBots = () => request('/bots');
exports.createBot = (payload) => request('/bots', { method: 'POST', body: JSON.stringify(payload) });
exports.updateBot = (id, payload) => request(`/bots/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
exports.deleteBot = (id) => request(`/bots/${id}`, { method: 'DELETE' });

exports.getPayments = () => request('/payments');
exports.createPayment = (payload) => request('/payments', { method: 'POST', body: JSON.stringify(payload) });
exports.activateSubscription = (payload) =>
  request('/subscriptions/activate', { method: 'POST', body: JSON.stringify(payload) });
