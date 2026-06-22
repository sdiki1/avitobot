import {
  checkPromoCode,
  getMiniappContent,
  getMonitorings,
  getPlans,
  getProfile,
  getSubscriptionPurchaseStatus,
  onboardingTrial,
  purchaseSubscription,
  updateMonitoring,
} from './api'
import {
  DEFAULT_MINIAPP_CONTENT,
  buildSubscriptionBotLink,
  hasMonitoringSettingsChanges,
  normalizeParamFlags,
  openExternal,
  SUBSCRIPTION_VIEW,
} from './appShared.jsx'

export async function loadDataAction({
  tgId,
  setProfile,
  setPlans,
  setMonitorings,
  setMiniappContent,
  setDrafts,
  setParamFlags,
  setSelectedMonitoringId,
}) {
  const [profileData, plansData, monitoringsData, contentData] = await Promise.all([
    getProfile(tgId),
    getPlans(),
    getMonitorings(tgId),
    getMiniappContent().catch(() => DEFAULT_MINIAPP_CONTENT),
  ])

  setProfile(profileData)
  setPlans(plansData)
  setMonitorings(monitoringsData)
  setMiniappContent(contentData || DEFAULT_MINIAPP_CONTENT)
  setDrafts((prev) => {
    const next = { ...prev }
    monitoringsData.forEach((item) => {
      const uid = String(item.id)
      next[uid] = {
        title: item.title || 'Подписка',
        url: item.url || '',
      }
    })
    return next
  })
  setParamFlags((prev) => {
    const next = { ...prev }
    monitoringsData.forEach((item) => {
      next[String(item.id)] = normalizeParamFlags(item)
    })
    return next
  })

  setSelectedMonitoringId((current) => {
    if (!current) return current
    const exists = monitoringsData.some((item) => String(item.id) === String(current))
    return exists ? current : null
  })
}

export async function applyPromoCodeAction({
  telegramId,
  selectedPlan,
  promoBusy,
  normalizedPromoCode,
  setPromoBusy,
  setPromoCode,
  setPromoPreview,
  setStatusMessage,
}) {
  if (!telegramId || !selectedPlan || promoBusy) return
  if (!normalizedPromoCode) {
    setPromoPreview(null)
    setStatusMessage('Введите промокод')
    return
  }

  try {
    setPromoBusy(true)
    const result = await checkPromoCode({
      telegram_id: Number(telegramId),
      plan_id: Number(selectedPlan.id),
      promo_code: normalizedPromoCode,
    })
    setPromoCode(result.code || normalizedPromoCode)
    setPromoPreview({ ...result, plan_id: Number(selectedPlan.id) })
    setStatusMessage(`Промокод применен. Скидка: ${Number(result.discount_rub || 0)} ₽`)
  } catch (error) {
    setPromoPreview(null)
    const detail = error?.response?.data?.detail || error?.message || 'Промокод не применен'
    setStatusMessage(`Ошибка: ${detail}`)
  } finally {
    setPromoBusy(false)
  }
}

export async function purchaseSubscriptionAction({
  telegramId,
  selectedPlan,
  purchaseBusy,
  normalizedPromoCode,
  activePromoPreview,
  selectedType,
  useReferralBalance,
  buyTargetMonitoringId,
  buyDraft,
  setPurchaseBusy,
  setPendingPaymentId,
  setPendingPaymentUrl,
  setStatusMessage,
  setSubscriptionView,
  loadData,
  totalPrice,
}) {
  if (!telegramId || !selectedPlan || purchaseBusy) return
  if (normalizedPromoCode && !activePromoPreview) {
    setStatusMessage('Нажмите «Применить промокод», чтобы пересчитать сумму')
    return
  }

  try {
    setPurchaseBusy(true)
    const result = await purchaseSubscription({
      telegram_id: Number(telegramId),
      plan_id: Number(selectedPlan.id),
      subscription_type: selectedType,
      use_referral_balance: useReferralBalance,
      promo_code: activePromoPreview ? normalizedPromoCode : null,
      monitoring_id: buyTargetMonitoringId ? Number(buyTargetMonitoringId) : null,
      monitoring_title: buyDraft.title || null,
      monitoring_url: buyDraft.url || null,
    })

    if (result?.requires_payment) {
      const paymentId = Number(result?.payment_id || 0)
      const paymentUrl = String(result?.payment_url || '').trim()
      if (!paymentId || !paymentUrl) {
        setStatusMessage('Ошибка: не удалось получить ссылку оплаты')
        return
      }
      setPendingPaymentId(paymentId)
      setPendingPaymentUrl(paymentUrl)
      setStatusMessage('Платеж создан. Завершите оплату и затем нажмите «Проверить оплату».')
      openExternal(paymentUrl)
      return
    }

    setPendingPaymentId(null)
    setPendingPaymentUrl('')
    await loadData(telegramId)
    setStatusMessage(
      `Подписка активирована: ${selectedPlan.name}. Итог к оплате: ${result?.amount_rub ?? totalPrice} ₽`,
    )
    setSubscriptionView(buyTargetMonitoringId ? SUBSCRIPTION_VIEW.detail : SUBSCRIPTION_VIEW.home)
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || 'Ошибка покупки подписки'
    setStatusMessage(`Ошибка: ${detail}`)
  } finally {
    setPurchaseBusy(false)
  }
}

export async function checkPurchaseStatusAction({
  explicitPaymentId = null,
  explicitTelegramId = null,
  pendingPaymentId,
  telegramId,
  purchaseStatusBusy,
  buyTargetMonitoringId,
  setPurchaseStatusBusy,
  setPendingPaymentId,
  setPendingPaymentUrl,
  setStatusMessage,
  setSubscriptionView,
  loadData,
}) {
  const paymentId = Number(explicitPaymentId || pendingPaymentId || 0)
  const effectiveTelegramId = Number(explicitTelegramId || telegramId || 0)
  if (!effectiveTelegramId || !paymentId || purchaseStatusBusy) return

  try {
    setPurchaseStatusBusy(true)
    const result = await getSubscriptionPurchaseStatus(effectiveTelegramId, paymentId)
    const paymentUrl = String(result?.payment_url || '').trim()
    if (paymentUrl) setPendingPaymentUrl(paymentUrl)

    if (result?.requires_payment) {
      setPendingPaymentId(paymentId)
      const statusText = result?.payment_status || 'pending'
      setStatusMessage(`Платеж ожидает оплаты (${statusText}).`)
      return
    }

    if (result?.ok && result?.subscription_id) {
      setPendingPaymentId(null)
      setPendingPaymentUrl('')
      await loadData(effectiveTelegramId)
      setStatusMessage(`Оплата подтверждена. Подписка активирована.`)
      setSubscriptionView(buyTargetMonitoringId ? SUBSCRIPTION_VIEW.detail : SUBSCRIPTION_VIEW.home)
      return
    }

    setPendingPaymentId(null)
    setPendingPaymentUrl('')
    setStatusMessage(result?.message || `Статус платежа: ${result?.payment_status || 'неизвестно'}`)
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || 'Ошибка проверки оплаты'
    setStatusMessage(`Ошибка: ${detail}`)
  } finally {
    setPurchaseStatusBusy(false)
  }
}

export async function activateTrialAction({
  telegramId,
  trialBusy,
  trialLabel,
  setTrialBusy,
  setStatusMessage,
  loadData,
}) {
  if (!telegramId || trialBusy) return

  try {
    setTrialBusy(true)
    const result = await onboardingTrial({ telegram_id: Number(telegramId) })
    await loadData(telegramId)
    if (result?.granted) {
      setStatusMessage(`Пробный период ${trialLabel} активирован`)
    } else {
      setStatusMessage('Пробный период уже использован или недоступен')
    }
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || 'Ошибка активации пробного периода'
    setStatusMessage(`Ошибка: ${detail}`)
  } finally {
    setTrialBusy(false)
  }
}

export async function persistMonitoringSettingsAction({
  telegramId,
  monitoring,
  draft,
  flags,
  extraPatch = {},
  force = false,
  applyMonitoringUpdateToState,
}) {
  if (!telegramId || !monitoring || monitoring.virtual) return monitoring

  const hasSettingsChanges = hasMonitoringSettingsChanges(monitoring, draft, flags)
  const hasExtraPatch = Object.keys(extraPatch).length > 0
  if (!force && !hasSettingsChanges && !hasExtraPatch) {
    return monitoring
  }

  const updated = await updateMonitoring(monitoring.id, {
    telegram_id: Number(telegramId),
    title: draft?.title || null,
    url: draft?.url || '',
    include_photo: Boolean(flags?.photo),
    include_description: Boolean(flags?.description),
    include_seller_info: Boolean(flags?.seller),
    notify_price_drop: Boolean(flags?.price_drop),
    detect_repost: Boolean(flags?.repost),
    ...extraPatch,
  })
  applyMonitoringUpdateToState(updated)
  return updated
}

export async function stopSelectedMonitoringAction({
  telegramId,
  selectedMonitoring,
  stopMonitoringBusy,
  drafts,
  paramFlags,
  setStopMonitoringBusy,
  setStatusMessage,
  persistMonitoringSettings,
}) {
  if (!telegramId || !selectedMonitoring || selectedMonitoring.virtual || stopMonitoringBusy) return
  if (!selectedMonitoring.is_active) {
    setStatusMessage('Мониторинг уже остановлен')
    return
  }

  const draft = drafts[selectedMonitoring.uid] || { title: selectedMonitoring.title || '', url: selectedMonitoring.url || '' }
  const flags = paramFlags[selectedMonitoring.uid] || normalizeParamFlags(selectedMonitoring)
  try {
    setStopMonitoringBusy(true)
    await persistMonitoringSettings({
      monitoring: selectedMonitoring,
      draft,
      flags,
      extraPatch: { is_active: false },
      force: true,
    })
    setStatusMessage('Мониторинг остановлен')
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || 'Ошибка остановки мониторинга'
    setStatusMessage(`Ошибка: ${detail}`)
  } finally {
    setStopMonitoringBusy(false)
  }
}

export async function startSelectedMonitoringAndOpenBotAction({
  telegramId,
  selectedMonitoring,
  startMonitoringBusy,
  stopMonitoringBusy,
  saveMonitoringBusy,
  drafts,
  paramFlags,
  setStartMonitoringBusy,
  setStatusMessage,
  persistMonitoringSettings,
}) {
  if (!telegramId || !selectedMonitoring || selectedMonitoring.virtual || startMonitoringBusy || stopMonitoringBusy || saveMonitoringBusy) return
  const detailBotLink = buildSubscriptionBotLink(selectedMonitoring.bot)
  if (!detailBotLink) {
    setStatusMessage('Для этой подписки бот пока не назначен')
    return
  }

  const draft = drafts[selectedMonitoring.uid] || { title: selectedMonitoring.title || '', url: selectedMonitoring.url || '' }
  const flags = paramFlags[selectedMonitoring.uid] || normalizeParamFlags(selectedMonitoring)
  const shouldStart = !selectedMonitoring.is_active
  try {
    setStartMonitoringBusy(true)
    await persistMonitoringSettings({
      monitoring: selectedMonitoring,
      draft,
      flags,
      extraPatch: shouldStart ? { is_active: true } : {},
    })
    setStatusMessage(shouldStart ? 'Мониторинг запущен. Переходим в бота…' : 'Переходим в бота…')
    openExternal(detailBotLink)
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || 'Ошибка запуска мониторинга'
    setStatusMessage(`Ошибка: ${detail}`)
  } finally {
    setStartMonitoringBusy(false)
  }
}

export async function openBotWithAutoSaveAction({
  telegramId,
  selectedMonitoring,
  startMonitoringBusy,
  stopMonitoringBusy,
  saveMonitoringBusy,
  drafts,
  paramFlags,
  setStartMonitoringBusy,
  setStatusMessage,
  persistMonitoringSettings,
}) {
  if (!telegramId || !selectedMonitoring || selectedMonitoring.virtual || startMonitoringBusy || stopMonitoringBusy || saveMonitoringBusy) return
  const detailBotLink = buildSubscriptionBotLink(selectedMonitoring.bot)
  if (!detailBotLink) {
    setStatusMessage('Для этой подписки бот пока не назначен')
    return
  }

  const draft = drafts[selectedMonitoring.uid] || { title: selectedMonitoring.title || '', url: selectedMonitoring.url || '' }
  const flags = paramFlags[selectedMonitoring.uid] || normalizeParamFlags(selectedMonitoring)
  try {
    setStartMonitoringBusy(true)
    await persistMonitoringSettings({
      monitoring: selectedMonitoring,
      draft,
      flags,
    })
    openExternal(detailBotLink)
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || 'Ошибка сохранения настроек'
    setStatusMessage(`Ошибка: ${detail}`)
  } finally {
    setStartMonitoringBusy(false)
  }
}
