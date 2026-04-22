import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  getAuthSession,
  getMiniappContent,
  getMonitorings,
  getSubscriptionPurchaseStatus,
  onboardingTrial,
  getPlans,
  getProfile,
  purchaseSubscription,
  resolveAuthToken,
  signInMiniApp,
  updateMonitoring,
} from './api'

const TABS = {
  info: 'info',
  subscriptions: 'subscriptions',
  profile: 'profile',
}

const SUBSCRIPTION_VIEW = {
  home: 'home',
  detail: 'detail',
  buy: 'buy',
}

const TYPE_OPTIONS = [
  { id: 'standard', label: 'Обычная', hint: 'стандартный режим' },
  { id: 'speed', label: 'Ускоренная', hint: 'приоритетный режим' },
]

const PARAM_OPTIONS = [
  { key: 'photo', label: 'Фотография' },
  { key: 'description', label: 'Описание' },
  { key: 'seller', label: 'Информация о продавце' },
  { key: 'price_drop', label: 'Снижение цены' },
]

const DEFAULT_PARAM_FLAGS = {
  photo: true,
  description: true,
  seller: true,
  price_drop: true,
}

const DEFAULT_MINIAPP_CONTENT = {
  support_title: 'Поддержка',
  support_url: 'https://t.me/your_support',
  faq_title: 'Частые вопросы',
  faq_url: 'https://t.me/your_faq',
  news_title: 'Новостной канал',
  news_url: 'https://t.me/your_news',
  terms_title: 'Пользовательское соглашение',
  terms_url: 'https://t.me/your_terms',
  privacy_title: 'Политика конфиденциальности',
  privacy_url: 'https://t.me/your_privacy',
  subscriptions_title: 'Подписки',
  subscriptions_hint: 'Управление подписками и переход в назначенных ботов.',
  profile_title: 'Профиль',
  info_links: [
    { key: 'support', title: 'Поддержка', url: 'https://t.me/your_support' },
    { key: 'faq', title: 'Частые вопросы', url: 'https://t.me/your_faq' },
    { key: 'news', title: 'Новостной канал', url: 'https://t.me/your_news' },
    { key: 'terms', title: 'Пользовательское соглашение', url: 'https://t.me/your_terms' },
    { key: 'privacy', title: 'Политика конфиденциальности', url: 'https://t.me/your_privacy' },
  ],
}

function getTelegramInitData() {
  const webapp = window.Telegram?.WebApp
  if (!webapp) return null
  webapp.ready()
  if (!webapp.initData || typeof webapp.initData !== 'string') return null
  return webapp.initData
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

function formatDateTime(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU')
}

function buildSubscriptionBotLink(bot) {
  const base = bot?.bot_link
  if (!base) return null
  const separator = base.includes('?') ? '&' : '?'
  return `${base}${separator}start=subscription`
}

function openExternal(url) {
  if (!url) return
  const tg = window.Telegram?.WebApp
  if (tg?.openTelegramLink && /^https:\/\/t\.me\//i.test(url)) {
    tg.openTelegramLink(url)
    return
  }
  if (tg?.openLink) {
    tg.openLink(url)
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 8h10v12H8zM6 4h10v2H8v10H6z" fill="currentColor" />
    </svg>
  )
}

function IconHome() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 10.7L12 4l8 6.7V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-9.3z" fill="currentColor" />
    </svg>
  )
}

function IconTicket() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7a3 3 0 1 0 0 6v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4a3 3 0 1 0 0-6V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v0z" fill="currentColor" />
      <path d="M12 8v8" stroke="#150f24" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

function IconProfile() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="8" r="4" fill="currentColor" />
      <path d="M4 20c0-3.5 3.6-6 8-6s8 2.5 8 6" fill="currentColor" />
    </svg>
  )
}

function IconChevron() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 5l7 7-7 7" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function botShortName(bot) {
  if (bot?.bot_username) return `@${String(bot.bot_username).replace(/^@/, '')}`
  return bot?.name || 'Бот не назначен'
}

function isCurrentSubscription(subscription) {
  const status = String(subscription?.status || '').toLowerCase()
  if (status !== 'active') return false
  if (!subscription?.ends_at) return true
  const endsAtTs = new Date(subscription.ends_at).getTime()
  if (Number.isNaN(endsAtTs)) return true
  return endsAtTs > Date.now()
}

function getSubscriptionState(subscription) {
  const status = String(subscription?.status || '').toLowerCase()
  const isCurrent = isCurrentSubscription(subscription)
  const endsAtTs = subscription?.ends_at ? new Date(subscription.ends_at).getTime() : Number.NaN
  const endedByDate = Number.isFinite(endsAtTs) && endsAtTs <= Date.now()

  if (isCurrent) {
    if (subscription?.is_trial) return { label: 'Тест', tone: 'trial' }
    return { label: 'Активна', tone: 'active' }
  }
  if (status === 'expired' || (status === 'active' && endedByDate)) {
    return { label: 'Завершена', tone: 'expired' }
  }
  if (status === 'pending') return { label: 'Ожидает', tone: 'pending' }
  return { label: status ? status.toUpperCase() : 'Неизвестно', tone: 'neutral' }
}

function subscriptionTitle(subscription) {
  const planName = subscription?.plan_name || 'Без тарифа'
  return subscription?.is_trial ? `${planName} (тест)` : planName
}

function normalizePlanName(value) {
  return String(value || '').trim().toLowerCase()
}

function detectPlanType(plan) {
  const byFormat = String(plan?.plan_format || '').trim().toLowerCase()
  if (byFormat.startsWith('speed') || byFormat.startsWith('ускор') || byFormat.startsWith('скорост')) return 'speed'
  if (byFormat.startsWith('standard') || byFormat.startsWith('обыч') || byFormat.startsWith('стандарт')) return 'standard'
  const normalized = normalizePlanName(plan?.name)
  if (normalized.startsWith('скорост') || normalized.startsWith('ускор')) return 'speed'
  return 'standard'
}

function getPlanDurationLabel(plan) {
  const label = String(plan?.duration_label || '').trim()
  if (label) return label
  return `${Number(plan?.duration_days || 0)} дней`
}

function normalizeParamFlags(monitoring) {
  return {
    photo: monitoring?.include_photo ?? true,
    description: monitoring?.include_description ?? true,
    seller: monitoring?.include_seller_info ?? true,
    price_drop: monitoring?.notify_price_drop ?? true,
  }
}

function normalizeDraftTitle(value) {
  return String(value || '').trim()
}

function normalizeDraftUrl(value) {
  return String(value || '').trim()
}

function hasMonitoringSettingsChanges(monitoring, draft, flags) {
  if (!monitoring) return false

  const currentTitle = normalizeDraftTitle(draft?.title)
  const currentUrl = normalizeDraftUrl(draft?.url)
  const sourceTitle = normalizeDraftTitle(monitoring.title)
  const sourceUrl = normalizeDraftUrl(monitoring.url)

  if (currentTitle !== sourceTitle) return true
  if (currentUrl !== sourceUrl) return true
  if (Boolean(flags?.photo) !== Boolean(monitoring.include_photo)) return true
  if (Boolean(flags?.description) !== Boolean(monitoring.include_description)) return true
  if (Boolean(flags?.seller) !== Boolean(monitoring.include_seller_info)) return true
  if (Boolean(flags?.price_drop) !== Boolean(monitoring.notify_price_drop)) return true
  return false
}

export default function App() {
  const [tab, setTab] = useState(TABS.subscriptions)
  const [subscriptionView, setSubscriptionView] = useState(SUBSCRIPTION_VIEW.home)
  const [telegramId, setTelegramId] = useState(null)

  const [loading, setLoading] = useState(true)
  const [statusMessage, setStatusMessage] = useState('')
  const [plans, setPlans] = useState([])
  const [profile, setProfile] = useState(null)
  const [monitorings, setMonitorings] = useState([])
  const [miniappContent, setMiniappContent] = useState(DEFAULT_MINIAPP_CONTENT)

  const [selectedMonitoringId, setSelectedMonitoringId] = useState(null)
  const [drafts, setDrafts] = useState({})
  const [paramFlags, setParamFlags] = useState({})

  const [purchaseBusy, setPurchaseBusy] = useState(false)
  const [purchaseStatusBusy, setPurchaseStatusBusy] = useState(false)
  const [trialBusy, setTrialBusy] = useState(false)
  const [saveMonitoringBusy, setSaveMonitoringBusy] = useState(false)
  const [startMonitoringBusy, setStartMonitoringBusy] = useState(false)
  const [stopMonitoringBusy, setStopMonitoringBusy] = useState(false)
  const [autoSaveStatus, setAutoSaveStatus] = useState('idle')
  const [pendingPaymentId, setPendingPaymentId] = useState(null)
  const [pendingPaymentUrl, setPendingPaymentUrl] = useState('')
  const [selectedType, setSelectedType] = useState(TYPE_OPTIONS[0].id)
  const [selectedPlanId, setSelectedPlanId] = useState(null)
  const [useReferralBalance, setUseReferralBalance] = useState(false)
  const [buyDraft, setBuyDraft] = useState({ title: '', url: '' })
  const [buyTargetMonitoringId, setBuyTargetMonitoringId] = useState(null)
  const [allSubscriptionsExpanded, setAllSubscriptionsExpanded] = useState(true)

  useEffect(() => {
    if (window.Telegram && window.Telegram.WebApp) {
      window.Telegram.WebApp.ready?.()
      window.Telegram.WebApp.expand()
    }
  }, [])

  const normalizedMonitorings = useMemo(() => {
    if (monitorings.length > 0) {
      return monitorings.map((item) => ({ ...item, uid: String(item.id) }))
    }

    return []
  }, [monitorings])

  const selectedMonitoring = useMemo(
    () => normalizedMonitorings.find((item) => item.uid === selectedMonitoringId) || null,
    [normalizedMonitorings, selectedMonitoringId],
  )

  const plansBySelectedType = useMemo(() => {
    return plans
      .filter((plan) => detectPlanType(plan) === selectedType)
      .sort((a, b) => {
        const byDuration = Number(a.duration_days || 0) - Number(b.duration_days || 0)
        if (byDuration !== 0) return byDuration
        const byPrice = Number(a.price_rub || 0) - Number(b.price_rub || 0)
        if (byPrice !== 0) return byPrice
        return Number(a.id || 0) - Number(b.id || 0)
      })
  }, [plans, selectedType])

  useEffect(() => {
    if (!plans.length) return
    const hasCurrentType = plans.some((plan) => detectPlanType(plan) === selectedType)
    if (!hasCurrentType) {
      setSelectedType(detectPlanType(plans[0]))
    }
  }, [plans, selectedType])

  useEffect(() => {
    if (plansBySelectedType.length === 0) {
      setSelectedPlanId(null)
      return
    }
    const hasSelected = plansBySelectedType.some((plan) => Number(plan.id) === Number(selectedPlanId))
    if (!hasSelected) {
      setSelectedPlanId(Number(plansBySelectedType[0].id))
    }
  }, [plansBySelectedType, selectedPlanId])

  const selectedPlan = useMemo(() => {
    if (plansBySelectedType.length === 0) return plans[0] || null
    const byId = plansBySelectedType.find((plan) => Number(plan.id) === Number(selectedPlanId))
    return byId || plansBySelectedType[0]
  }, [plans, plansBySelectedType, selectedPlanId])

  const selectedPlanDurationLabel = useMemo(() => {
    if (!selectedPlan) return '—'
    return getPlanDurationLabel(selectedPlan)
  }, [selectedPlan])

  const referralBalance = profile?.user?.referral_balance_rub ?? 0
  const basePrice = Number(selectedPlan?.price_rub || 0)
  const totalBeforeReferral = Math.max(0, basePrice)
  const totalPrice = Math.max(0, totalBeforeReferral - (useReferralBalance ? referralBalance : 0))

  const loadData = async (tgId) => {
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

  useEffect(() => {
    const init = async () => {
      try {
        let resolvedTelegramId = null
        let authError = false

        const initData = getTelegramInitData()
        if (initData) {
          try {
            const payload = await signInMiniApp(initData)
            resolvedTelegramId = Number(payload.telegram_id)
          } catch {
            authError = true
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
          } catch {
            authError = true
          }
        }

        if (!resolvedTelegramId) {
          setStatusMessage(
            authError
              ? 'Ошибка: не удалось авторизоваться через Telegram'
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
      } catch (error) {
        const detail = error?.response?.data?.detail || error?.message || 'Ошибка инициализации'
        setStatusMessage(`Ошибка: ${detail}`)
      } finally {
        setLoading(false)
      }
    }

    init()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const copyText = async (value, successText) => {
    if (!value) return
    try {
      await navigator.clipboard.writeText(String(value))
      setStatusMessage(successText)
    } catch {
      setStatusMessage('Не удалось скопировать')
    }
  }

  const ensureDraft = (monitoring) => {
    const uid = String(monitoring.uid)
    setDrafts((prev) => {
      if (prev[uid]) return prev
      return {
        ...prev,
        [uid]: {
          title: monitoring.title || 'Подписка',
          url: monitoring.url || '',
        },
      }
    })

    setParamFlags((prev) => {
      if (prev[uid]) return prev
      return {
        ...prev,
        [uid]: normalizeParamFlags(monitoring),
      }
    })
  }

  const openSubscriptionDetails = (monitoring) => {
    ensureDraft(monitoring)
    setSelectedMonitoringId(String(monitoring.uid))
    setSubscriptionView(SUBSCRIPTION_VIEW.detail)
  }

  const openBuyScreen = ({ renew = false } = {}) => {
    if (renew && selectedMonitoring) {
      ensureDraft(selectedMonitoring)
      const draft = drafts[selectedMonitoring.uid] || {
        title: selectedMonitoring.title || '',
        url: selectedMonitoring.url || '',
      }
      setBuyDraft({ title: draft.title || '', url: draft.url || '' })
      setBuyTargetMonitoringId(Number(selectedMonitoring.id))
    } else {
      setBuyDraft({ title: '', url: '' })
      setBuyTargetMonitoringId(null)
    }
    setSubscriptionView(SUBSCRIPTION_VIEW.buy)
  }

  const handleBackNavigation = useCallback(() => {
    if (tab !== TABS.subscriptions) {
      setTab(TABS.subscriptions)
      setSubscriptionView(SUBSCRIPTION_VIEW.home)
      return
    }

    if (subscriptionView === SUBSCRIPTION_VIEW.detail) {
      setSubscriptionView(SUBSCRIPTION_VIEW.home)
      return
    }

    if (subscriptionView === SUBSCRIPTION_VIEW.buy) {
      setSubscriptionView(buyTargetMonitoringId ? SUBSCRIPTION_VIEW.detail : SUBSCRIPTION_VIEW.home)
      return
    }

    window.Telegram?.WebApp?.close?.()
  }, [buyTargetMonitoringId, subscriptionView, tab])

  const onPurchase = async () => {
    if (!telegramId || !selectedPlan || purchaseBusy) return
    try {
      setPurchaseBusy(true)
      const result = await purchaseSubscription({
        telegram_id: Number(telegramId),
        plan_id: Number(selectedPlan.id),
        subscription_type: selectedType,
        use_referral_balance: useReferralBalance,
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

        if (window.Telegram?.WebApp?.openLink) {
          window.Telegram.WebApp.openLink(paymentUrl)
        } else {
          openExternal(paymentUrl)
        }
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

  const checkPurchaseStatus = async (explicitPaymentId = null, explicitTelegramId = null) => {
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

  const onActivateTrial = async () => {
    if (!telegramId || trialBusy) return
    try {
      setTrialBusy(true)
      const result = await onboardingTrial({ telegram_id: Number(telegramId) })
      await loadData(telegramId)
      if (result?.granted) {
        setStatusMessage('Пробный период 24 часа активирован')
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

  const applyMonitoringUpdateToState = useCallback((updatedMonitoring) => {
    if (!updatedMonitoring?.id) return
    const uid = String(updatedMonitoring.id)

    setMonitorings((prev) =>
      prev.map((item) => (Number(item.id) === Number(updatedMonitoring.id) ? updatedMonitoring : item)),
    )
    setDrafts((prev) => ({
      ...prev,
      [uid]: {
        title: updatedMonitoring.title || '',
        url: updatedMonitoring.url || '',
      },
    }))
    setParamFlags((prev) => ({
      ...prev,
      [uid]: normalizeParamFlags(updatedMonitoring),
    }))
  }, [])

  const persistMonitoringSettings = useCallback(
    async ({ monitoring, draft, flags, extraPatch = {}, force = false }) => {
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
        ...extraPatch,
      })
      applyMonitoringUpdateToState(updated)
      return updated
    },
    [applyMonitoringUpdateToState, telegramId],
  )

  const stopSelectedMonitoring = async () => {
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

  const startSelectedMonitoringAndOpenBot = async () => {
    if (!telegramId || !selectedMonitoring || selectedMonitoring.virtual || startMonitoringBusy || stopMonitoringBusy || saveMonitoringBusy) return
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

  const openBotWithAutoSave = async () => {
    if (!telegramId || !selectedMonitoring || selectedMonitoring.virtual || startMonitoringBusy || stopMonitoringBusy || saveMonitoringBusy) return
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

  const updateSelectedDraft = (patch) => {
    if (!selectedMonitoring) return
    setDrafts((prev) => ({
      ...prev,
      [selectedMonitoring.uid]: {
        ...(prev[selectedMonitoring.uid] || { title: '', url: '' }),
        ...patch,
      },
    }))
  }

  useEffect(() => {
    const backButton = window.Telegram?.WebApp?.BackButton
    if (!backButton) return

    const canGoBack = tab !== TABS.subscriptions || subscriptionView !== SUBSCRIPTION_VIEW.home
    if (canGoBack) backButton.show()
    else backButton.hide()

    backButton.onClick(handleBackNavigation)
    return () => {
      backButton.offClick(handleBackNavigation)
      backButton.hide()
    }
  }, [handleBackNavigation, subscriptionView, tab])

  const activeInfoLinks = miniappContent?.info_links?.length
    ? miniappContent.info_links
    : DEFAULT_MINIAPP_CONTENT.info_links

  const detailDraft = selectedMonitoring
    ? drafts[selectedMonitoring.uid] || {
        title: selectedMonitoring.title || '',
        url: selectedMonitoring.url || '',
      }
    : { title: '', url: '' }

  const detailFlags = selectedMonitoring
    ? paramFlags[selectedMonitoring.uid] || normalizeParamFlags(selectedMonitoring)
    : DEFAULT_PARAM_FLAGS

  const detailBotLink = selectedMonitoring ? buildSubscriptionBotLink(selectedMonitoring.bot) : null
  const profileSubscriptions = Array.isArray(profile?.subscriptions) ? profile.subscriptions : []
  const profileCurrentSubscriptions = profileSubscriptions.filter((item) => isCurrentSubscription(item))
  const fallbackCurrentSubscriptions =
    profileCurrentSubscriptions.length > 0
      ? profileCurrentSubscriptions
      : profile?.subscription
        ? [profile.subscription]
        : []
  const assignedBots = Array.isArray(profile?.assigned_bots) ? profile.assigned_bots : []

  useEffect(() => {
    if (!telegramId || !selectedMonitoring || selectedMonitoring.virtual) {
      setAutoSaveStatus('idle')
      return
    }
    if (startMonitoringBusy || stopMonitoringBusy) {
      return
    }

    const draft = drafts[selectedMonitoring.uid] || { title: selectedMonitoring.title || '', url: selectedMonitoring.url || '' }
    const flags = paramFlags[selectedMonitoring.uid] || normalizeParamFlags(selectedMonitoring)
    if (!hasMonitoringSettingsChanges(selectedMonitoring, draft, flags)) {
      setAutoSaveStatus('idle')
      return
    }

    const timerId = setTimeout(async () => {
      if (saveMonitoringBusy || startMonitoringBusy || stopMonitoringBusy) return
      try {
        setSaveMonitoringBusy(true)
        setAutoSaveStatus('saving')
        await persistMonitoringSettings({
          monitoring: selectedMonitoring,
          draft,
          flags,
        })
        setAutoSaveStatus('saved')
      } catch (error) {
        const detail = error?.response?.data?.detail || error?.message || 'Ошибка автосохранения'
        setAutoSaveStatus('error')
        setStatusMessage(`Ошибка: ${detail}`)
      } finally {
        setSaveMonitoringBusy(false)
      }
    }, 700)

    return () => clearTimeout(timerId)
  }, [
    drafts,
    paramFlags,
    persistMonitoringSettings,
    saveMonitoringBusy,
    selectedMonitoring,
    startMonitoringBusy,
    stopMonitoringBusy,
    telegramId,
  ])

  return (
    <div className="app-root">
      <div className="mobile-shell">
        <main className="main-content">
          {statusMessage && <div className="status-banner">{statusMessage}</div>}

          {loading && (
            <section className="screen-block">
              <div className="empty-card">Загрузка...</div>
            </section>
          )}

          {!loading && tab === TABS.info && (
            <section className="screen-block">
              <h1 className="screen-title">Информация</h1>
              <div className="info-links">
                {activeInfoLinks.map((item) => (
                  <a key={item.key} href={item.url} target="_blank" rel="noreferrer" className="info-link-card">
                    <span>{item.title}</span>
                    <span className="link-arrow">→</span>
                  </a>
                ))}
              </div>
            </section>
          )}

          {!loading && tab === TABS.subscriptions && subscriptionView === SUBSCRIPTION_VIEW.home && (
            <section className="screen-block screen-subscriptions-home">
              <h1 className="screen-title">{miniappContent?.subscriptions_title || 'Подписки'}</h1>

              <div className="subscription-list">
                {normalizedMonitorings.length === 0 && (
                  <div className="empty-card">У вас пока нет мониторингов. Нажмите «Купить подписку».</div>
                )}

                {normalizedMonitorings.map((monitoring) => (
                  <button
                    key={monitoring.uid}
                    type="button"
                    className="subscription-card"
                    onClick={() => openSubscriptionDetails(monitoring)}
                  >
                    <span className="subscription-avatar">◉</span>

                    <span className="subscription-body">
                      <strong>{monitoring.title || 'Мониторинг'}</strong>
                      <span>
                        {botShortName(monitoring.bot)} • {monitoring.is_active ? 'в работе' : 'остановлен'} •{' '}
                        {monitoring.link_configured ? 'ссылка задана' : 'ссылка не задана'}
                      </span>
                    </span>

                    <span className="subscription-chevron">
                      <IconChevron />
                    </span>
                  </button>
                ))}
              </div>

              <button
                type="button"
                className="primary-btn purchase-bottom-btn"
                onClick={() => openBuyScreen({ renew: false })}
              >
                Купить подписку
              </button>
            </section>
          )}

          {!loading && tab === TABS.subscriptions && subscriptionView === SUBSCRIPTION_VIEW.detail && (
            <section className="screen-block">
              {!selectedMonitoring && (
                <div className="empty-card">Подписка не выбрана. Перейдите в список подписок.</div>
              )}

              {selectedMonitoring && (
                <>
                  <h1 className="screen-title">{detailDraft.title || selectedMonitoring.title || 'Подписка'}</h1>

                  <h2 className="section-title">Настройки подписки</h2>
                  <input
                    type="text"
                    className="dark-input"
                    placeholder="Введите название подписки"
                    value={detailDraft.title}
                    disabled={selectedMonitoring.virtual}
                    onChange={(event) => updateSelectedDraft({ title: event.target.value })}
                  />

                  <input
                    type="text"
                    className="dark-input"
                    placeholder="Укажите ссылку на объявления"
                    value={detailDraft.url}
                    disabled={selectedMonitoring.virtual}
                    onChange={(event) => updateSelectedDraft({ url: event.target.value })}
                  />

                  <p className="hint-text">Ссылка на объявления — это поисковая ссылка, которая выводит все объявления при поиске.</p>

                  <button type="button" className="primary-btn" onClick={() => openBuyScreen({ renew: true })}>
                    Продлить подписку →
                  </button>

                  <h2 className="section-title">Параметры</h2>
                  <div className="checks-list">
                    {PARAM_OPTIONS.map((option) => (
                      <button
                        key={option.key}
                        type="button"
                        className="check-row"
                        onClick={() =>
                          setParamFlags((prev) => ({
                            ...prev,
                            [selectedMonitoring.uid]: {
                              ...detailFlags,
                              [option.key]: !detailFlags[option.key],
                            },
                          }))
                        }
                      >
                        <span className={`check-box ${detailFlags[option.key] ? 'checked' : ''}`} />
                        <span>{option.label}</span>
                      </button>
                    ))}
                  </div>

                  <p
                    className={`hint-text ${
                      autoSaveStatus === 'error' ? 'hint-error' : autoSaveStatus === 'saved' ? 'hint-success' : ''
                    }`}
                  >
                    {autoSaveStatus === 'saving' && 'Сохраняем изменения...'}
                    {autoSaveStatus === 'saved' && 'Изменения сохранены автоматически'}
                    {autoSaveStatus === 'error' && 'Ошибка автосохранения. Попробуйте еще раз'}
                    {autoSaveStatus === 'idle' && 'Все изменения сохраняются автоматически'}
                  </p>

                  {!selectedMonitoring.virtual && (
                    <button
                      type="button"
                      className="danger-btn"
                      onClick={stopSelectedMonitoring}
                      disabled={stopMonitoringBusy || saveMonitoringBusy || !selectedMonitoring.is_active}
                    >
                      {stopMonitoringBusy
                        ? 'Останавливаем...'
                        : selectedMonitoring.is_active
                          ? 'Остановить мониторинг'
                          : 'Мониторинг остановлен'}
                    </button>
                  )}

                  <p className="hint-text">
                    Перед первым запуском не забудь{' '}
                    <a href={detailBotLink || '#'} target="_blank" rel="noreferrer">
                      запустить бота отправителя
                    </a>
                  </p>

                  <button
                    type="button"
                    className="primary-btn"
                    onClick={startSelectedMonitoringAndOpenBot}
                    disabled={startMonitoringBusy || stopMonitoringBusy || saveMonitoringBusy}
                  >
                    {startMonitoringBusy ? 'Запускаем...' : 'Запустить мониторинг и перейти в бота'}
                  </button>

                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={openBotWithAutoSave}
                    disabled={startMonitoringBusy || stopMonitoringBusy || saveMonitoringBusy}
                  >
                    Перейти в бота отправителя
                  </button>
                </>
              )}
            </section>
          )}

          {!loading && tab === TABS.subscriptions && subscriptionView === SUBSCRIPTION_VIEW.buy && (
            <section className="screen-block">
              <h1 className="screen-title">Покупка подписки</h1>

              <h2 className="section-title">Тип подписки</h2>
              <div className="choices-list">
                {TYPE_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className={`choice-row ${selectedType === option.id ? 'active' : ''}`}
                    onClick={() => {
                      setSelectedType(option.id)
                      setSelectedPlanId(null)
                    }}
                  >
                    <span className="choice-dot" />
                    <span className="choice-main">{option.label}</span>
                    <span className="choice-meta">({option.hint})</span>
                  </button>
                ))}
              </div>

              <h2 className="section-title">Срок и стоимость</h2>
              <div className="choices-list">
                {plansBySelectedType.length === 0 && (
                  <div className="empty-card">Для выбранного формата тарифы пока не настроены.</div>
                )}
                {plansBySelectedType.map((plan) => (
                  <button
                    key={plan.id}
                    type="button"
                    className={`choice-row ${Number(selectedPlan?.id) === Number(plan.id) ? 'active' : ''}`}
                    onClick={() => setSelectedPlanId(Number(plan.id))}
                  >
                    <span className="choice-dot" />
                    <span className="choice-main">{getPlanDurationLabel(plan)}</span>
                    <span className="choice-meta">{Number(plan.price_rub || 0)} ₽ · {Number(plan.duration_days || 0)} дн.</span>
                  </button>
                ))}
              </div>

              <h2 className="section-title">Настройки подписки</h2>
              <input
                type="text"
                className="dark-input"
                placeholder="Введите название подписки"
                value={buyDraft.title}
                onChange={(event) => setBuyDraft((prev) => ({ ...prev, title: event.target.value }))}
              />

              <input
                type="text"
                className="dark-input"
                placeholder="Укажите ссылку на объявления"
                value={buyDraft.url}
                onChange={(event) => setBuyDraft((prev) => ({ ...prev, url: event.target.value }))}
              />

              <p className="hint-text">Укажите поисковую URL-ссылку на список объявлений из адресной строки браузера.</p>

              <div className="buy-summary">
                <div className="summary-balance">Тариф: {selectedPlan?.name || '—'}</div>
                <div className="summary-balance">Срок: {selectedPlanDurationLabel} ({selectedPlan?.duration_days ?? 0} дней)</div>
                <div className="summary-balance">Цена тарифа: {basePrice}₽</div>
                <div className="summary-total">Итог: {totalPrice}₽</div>
                <div className="summary-balance">Реф. баланс: {referralBalance}₽</div>
                <button
                  type="button"
                  className="check-row balance-row"
                  onClick={() => setUseReferralBalance((prev) => !prev)}
                >
                  <span className={`check-box ${useReferralBalance ? 'checked' : ''}`} />
                  <span>Использовать реф. баланс для оплаты</span>
                </button>
              </div>

              {profile?.can_activate_trial && (
                <button type="button" className="secondary-btn" onClick={onActivateTrial} disabled={trialBusy}>
                  {trialBusy ? 'Активация...' : 'Включить пробный период 24 часа'}
                </button>
              )}

              {pendingPaymentId && (
                <div className="buy-summary">
                  <div className="summary-balance">Ожидает оплаты: платеж #{pendingPaymentId}</div>
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => checkPurchaseStatus()}
                    disabled={purchaseStatusBusy}
                  >
                    {purchaseStatusBusy ? 'Проверяем...' : 'Проверить оплату'}
                  </button>
                  {pendingPaymentUrl && (
                    <button
                      type="button"
                      className="secondary-btn"
                      onClick={() => {
                        if (window.Telegram?.WebApp?.openLink) {
                          window.Telegram.WebApp.openLink(pendingPaymentUrl)
                        } else {
                          openExternal(pendingPaymentUrl)
                        }
                      }}
                    >
                      Открыть оплату снова
                    </button>
                  )}
                </div>
              )}

              <button
                type="button"
                className="primary-btn"
                onClick={onPurchase}
                disabled={!selectedPlan || purchaseBusy || purchaseStatusBusy}
              >
                {purchaseBusy ? 'Создание платежа...' : 'Оплатить через ЮKassa (СБП)'}
              </button>
            </section>
          )}

          {!loading && tab === TABS.profile && (
            <section className="screen-block">
              <h1 className="screen-title">{miniappContent?.profile_title || 'Профиль'}</h1>

              <div className="profile-list">
                <div className="profile-row">
                  <span>Telegram ID</span>
                  <div>
                    <strong>{profile?.user?.telegram_id || telegramId || '—'}</strong>
                    <button
                      type="button"
                      className="icon-copy-btn"
                      onClick={() => copyText(profile?.user?.telegram_id || telegramId, 'Telegram ID скопирован')}
                    >
                      <CopyIcon />
                    </button>
                  </div>
                </div>

                <div className="profile-row">
                  <span>Реферальная ссылка</span>
                  <div>
                    <strong>{profile?.referral_link || profile?.user?.referral_code || '—'}</strong>
                    <button
                      type="button"
                      className="icon-copy-btn"
                      onClick={() =>
                        copyText(profile?.referral_link || profile?.user?.referral_code, 'Реферальная ссылка скопирована')
                      }
                    >
                      <CopyIcon />
                    </button>
                  </div>
                </div>

                <div className="profile-row">
                  <span>Реф. баланс</span>
                  <div>
                    <strong>{profile?.user?.referral_balance_rub ?? 0} ₽</strong>
                  </div>
                </div>

                <div className="profile-section">
                  <span className="profile-section-title">Текущие подписки</span>
                  {fallbackCurrentSubscriptions.length > 0 ? (
                    <div className="profile-subscriptions-grid">
                      {fallbackCurrentSubscriptions.map((sub, index) => {
                        const state = getSubscriptionState(sub)
                        return (
                          <article className="profile-subscription-card" key={sub?.id || `current-${index}`}>
                            <div className="profile-subscription-head">
                              <strong>{subscriptionTitle(sub)}</strong>
                              <span className={`profile-subscription-badge ${state.tone}`}>{state.label}</span>
                            </div>
                            <div className="profile-subscription-meta">
                              <span>До: {formatDateTime(sub?.ends_at)}</span>
                              <span>Лимит: {sub?.links_limit ?? 0}</span>
                              {typeof sub?.amount_paid === 'number' && <span>Оплата: {sub.amount_paid} ₽</span>}
                            </div>
                          </article>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="profile-empty-card">Нет активных подписок</div>
                  )}
                </div>

                <div className="profile-section">
                  <div className="profile-section-header">
                    <span className="profile-section-title">Все подписки</span>
                    <button
                      type="button"
                      className="profile-section-toggle"
                      onClick={() => setAllSubscriptionsExpanded((prev) => !prev)}
                    >
                      {allSubscriptionsExpanded ? 'Свернуть' : 'Развернуть'}
                    </button>
                  </div>
                  {allSubscriptionsExpanded &&
                    (profileSubscriptions.length > 0 ? (
                      <div className="profile-subscriptions-grid">
                        {profileSubscriptions.map((sub, index) => {
                          const state = getSubscriptionState(sub)
                          return (
                            <article className="profile-subscription-card" key={sub?.id || `all-${index}`}>
                              <div className="profile-subscription-head">
                                <strong>{subscriptionTitle(sub)}</strong>
                                <span className={`profile-subscription-badge ${state.tone}`}>{state.label}</span>
                              </div>
                              <div className="profile-subscription-meta">
                                <span>Начало: {formatDateTime(sub?.started_at)}</span>
                                <span>До: {formatDateTime(sub?.ends_at)}</span>
                                <span>Лимит: {sub?.links_limit ?? 0}</span>
                                <span>Оплата: {sub?.amount_paid ?? 0} ₽</span>
                              </div>
                            </article>
                          )
                        })}
                      </div>
                    ) : (
                      <div className="profile-empty-card">Нет подписок</div>
                    ))}
                </div>

                <div className="profile-section">
                  <span className="profile-section-title">Назначенные боты</span>
                  {assignedBots.length > 0 ? (
                    <div className="profile-bots-grid">
                      {assignedBots.map((bot, index) => {
                        const botLink = buildSubscriptionBotLink(bot) || bot?.bot_link || null
                        return (
                          <button
                            key={bot?.id || `bot-${index}`}
                            type="button"
                            className={`profile-bot-card ${botLink ? '' : 'disabled'}`}
                            onClick={() => {
                              if (!botLink) {
                                setStatusMessage('Для этого бота ссылка недоступна')
                                return
                              }
                              openExternal(botLink)
                            }}
                          >
                            <span className="profile-bot-main">
                              <strong>{bot?.name || 'Бот'}</strong>
                              <span>{botShortName(bot)}</span>
                            </span>
                            <span className="profile-bot-open">{botLink ? 'Открыть' : 'Недоступно'}</span>
                            <span className="profile-bot-chevron">
                              <IconChevron />
                            </span>
                          </button>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="profile-empty-card">Назначенных ботов нет</div>
                  )}
                </div>
              </div>
            </section>
          )}
        </main>

        <nav className="bottom-nav">
          <button
            type="button"
            className={`bottom-nav-item ${tab === TABS.info ? 'active' : ''}`}
            onClick={() => setTab(TABS.info)}
          >
            <span className="bottom-icon">
              <IconHome />
            </span>
            <span>Информация</span>
          </button>

          <button
            type="button"
            className={`bottom-nav-item ${tab === TABS.subscriptions ? 'active' : ''}`}
            onClick={() => {
              setTab(TABS.subscriptions)
              if (subscriptionView !== SUBSCRIPTION_VIEW.home) {
                setSubscriptionView(SUBSCRIPTION_VIEW.home)
              }
            }}
          >
            <span className="bottom-icon">
              <IconTicket />
            </span>
            <span>Подписки</span>
          </button>

          <button
            type="button"
            className={`bottom-nav-item ${tab === TABS.profile ? 'active' : ''}`}
            onClick={() => setTab(TABS.profile)}
          >
            <span className="bottom-icon">
              <IconProfile />
            </span>
            <span>Профиль</span>
          </button>
        </nav>
      </div>
    </div>
  )
}
