import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

const client = axios.create({
  baseURL: `${API_BASE}/v1/public`,
  timeout: 20000,
})

export async function authTelegramUser(payload) {
  const { data } = await client.post('/auth/telegram', payload)
  return data
}

export async function getPlans() {
  const { data } = await client.get('/plans')
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

export async function createMonitoring(payload) {
  const { data } = await client.post('/monitorings', payload)
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
