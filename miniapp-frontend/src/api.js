import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

const client = axios.create({
  baseURL: `${API_BASE}/v1/public`,
  timeout: 20000,
  withCredentials: true,
})

export async function authTelegramUser(payload) {
  const { data } = await client.post('/auth/telegram', payload)
  return data
}

export async function signInMiniApp(initData) {
  const { data } = await client.post('/auth/miniapp/signin', { init_data: initData })
  return data
}

export async function getAuthSession() {
  const { data } = await client.get('/auth/session')
  return data
}

export async function resolveAuthToken(authToken) {
  const { data } = await client.get('/auth/resolve', { params: { auth: authToken } })
  return data
}

export async function getPlans() {
  const { data } = await client.get('/plans')
  return data
}

export async function getMiniappContent() {
  const { data } = await client.get('/miniapp-content')
  return data
}

export async function getProfile(telegramId) {
  const { data } = await client.get('/profile', { params: { telegram_id: telegramId } })
  return data
}

export async function getMonitorings(telegramId) {
  const { data } = await client.get('/monitorings', { params: { telegram_id: telegramId } })
  return data
}

export async function updateMonitoring(monitoringId, payload) {
  const { data } = await client.patch(`/monitorings/${monitoringId}`, payload)
  return data
}

export async function createMonitoring(payload) {
  const { data } = await client.post('/monitorings', payload)
  return data
}

export async function purchaseMonitoring(payload) {
  const { data } = await client.post('/monitorings/purchase', payload)
  return data
}

export async function purchaseSubscription(payload) {
  const { data } = await client.post('/subscriptions/purchase', payload)
  return data
}

export async function onboardingTrial(payload) {
  const { data } = await client.post('/onboarding-trial', payload)
  return data
}

export async function deleteMonitoring(telegramId, monitoringId) {
  const { data } = await client.delete(`/monitorings/${monitoringId}`, {
    params: { telegram_id: telegramId },
  })
  return data
}

export async function getMonitoringItems(telegramId, monitoringId) {
  const { data } = await client.get(`/monitorings/${monitoringId}/items`, {
    params: { telegram_id: telegramId, limit: 50 },
  })
  return data
}

export async function getNotifications(telegramId) {
  const { data } = await client.get('/notifications', {
    params: { telegram_id: telegramId, limit: 20 },
  })
  return data
}
