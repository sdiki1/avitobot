import { getAuthSession, resolveAuthToken, signInMiniApp } from './api'

function getTelegramInitData() {
  const webapp = window.Telegram?.WebApp
  if (!webapp) return null
  webapp.ready()
  if (!webapp.initData || typeof webapp.initData !== 'string') return null
  return webapp.initData
}

function waitForTelegramWebApp(timeoutMs = 1500) {
  if (window.Telegram?.WebApp) return Promise.resolve()

  return new Promise((resolve) => {
    const startedAt = Date.now()
    const timerId = window.setInterval(() => {
      if (window.Telegram?.WebApp || Date.now() - startedAt >= timeoutMs) {
        window.clearInterval(timerId)
        resolve()
      }
    }, 50)
  })
}

function getAuthTokenFromQuery() {
  return new URLSearchParams(window.location.search).get('auth')
}

function getPaymentIdFromQuery() {
  const raw = new URLSearchParams(window.location.search).get('payment_id')
  const parsed = Number(raw)
  if (!Number.isFinite(parsed) || parsed <= 0) return null
  return Math.trunc(parsed)
}

function errorDetail(error) {
  return error?.response?.data?.detail || error?.message || ''
}

export async function initMiniAppSession({
  setStatusMessage,
  setTelegramId,
  setPendingPaymentId,
  loadData,
  checkPurchaseStatus,
}) {
  let resolvedTelegramId = null
  let authErrorMessage = ''

  await waitForTelegramWebApp()
  const initData = getTelegramInitData()
  if (initData) {
    try {
      const payload = await signInMiniApp(initData)
      resolvedTelegramId = Number(payload.telegram_id)
    } catch (error) {
      authErrorMessage = errorDetail(error) || 'не удалось авторизоваться через Telegram'
    }
  }

  if (!resolvedTelegramId) {
    try {
      const session = await getAuthSession()
      resolvedTelegramId = Number(session.telegram_id)
    } catch {
      // ignored: no active cookie session yet
    }
  }

  const authToken = getAuthTokenFromQuery()
  if (!resolvedTelegramId && authToken) {
    try {
      const payload = await resolveAuthToken(authToken)
      resolvedTelegramId = Number(payload.telegram_id)
    } catch (error) {
      authErrorMessage = errorDetail(error) || authErrorMessage
    }
  }

  if (!resolvedTelegramId) {
    setStatusMessage(
      authErrorMessage
        ? `Ошибка авторизации Telegram: ${authErrorMessage}`
        : 'Ошибка: откройте Mini App через Telegram',
    )
    return
  }

  setTelegramId(resolvedTelegramId)
  await loadData(resolvedTelegramId)

  const returnedPaymentId = getPaymentIdFromQuery()
  if (returnedPaymentId) {
    setPendingPaymentId(returnedPaymentId)
    await checkPurchaseStatus(returnedPaymentId, resolvedTelegramId)
  }
}
