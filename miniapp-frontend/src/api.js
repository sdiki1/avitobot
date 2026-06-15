const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'
const PUBLIC_API_BASE = `${API_BASE}/v1/public`

function buildUrl(path, params = null) {
  const url = new URL(`${PUBLIC_API_BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) url.searchParams.set(key, value)
    })
  }
  return url
}

async function request(path, { method = 'GET', body = null, params = null } = {}) {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 20000)

  try {
    const response = await fetch(buildUrl(path, params), {
      method,
      credentials: 'include',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
    const contentType = response.headers.get('content-type') || ''
    const data = contentType.includes('application/json') ? await response.json() : await response.text()

    if (!response.ok) {
      const detail = typeof data === 'object' && data ? data.detail : data
      const error = new Error(detail || `API ${response.status}`)
      error.response = { status: response.status, data }
      throw error
    }

    return data
  } finally {
    window.clearTimeout(timeoutId)
  }
}

export async function authTelegramUser(payload) {
  return request('/auth/telegram', { method: 'POST', body: payload })
}

export async function signInMiniApp(initData) {
  return request('/auth/miniapp/signin', { method: 'POST', body: { init_data: initData } })
}

export async function getAuthSession() {
  return request('/auth/session')
}

export async function resolveAuthToken(authToken) {
  return request('/auth/resolve', { params: { auth: authToken } })
}

export async function getPlans() {
  return request('/plans')
}

export async function getMiniappContent() {
  return request('/miniapp-content')
}

export async function getProfile(telegramId) {
  return request('/profile', { params: { telegram_id: telegramId } })
}

export async function getMonitorings(telegramId) {
  return request('/monitorings', { params: { telegram_id: telegramId } })
}

export async function updateMonitoring(monitoringId, payload) {
  return request(`/monitorings/${monitoringId}`, { method: 'PATCH', body: payload })
}

export async function createMonitoring(payload) {
  return request('/monitorings', { method: 'POST', body: payload })
}

export async function purchaseMonitoring(payload) {
  return request('/monitorings/purchase', { method: 'POST', body: payload })
}

export async function purchaseSubscription(payload) {
  return request('/subscriptions/purchase', { method: 'POST', body: payload })
}

export async function checkPromoCode(payload) {
  return request('/promo-codes/check', { method: 'POST', body: payload })
}

export async function getSubscriptionPurchaseStatus(telegramId, paymentId) {
  return request(`/subscriptions/purchase/${paymentId}/status`, { params: { telegram_id: telegramId } })
}

export async function onboardingTrial(payload) {
  return request('/onboarding-trial', { method: 'POST', body: payload })
}

export async function deleteMonitoring(telegramId, monitoringId) {
  return request(`/monitorings/${monitoringId}`, {
    method: 'DELETE',
    params: { telegram_id: telegramId },
  })
}

export async function getMonitoringItems(telegramId, monitoringId) {
  return request(`/monitorings/${monitoringId}/items`, {
    params: { telegram_id: telegramId, limit: 50 },
  })
}

export async function getNotifications(telegramId) {
  return request('/notifications', {
    params: { telegram_id: telegramId, limit: 20 },
  })
}
