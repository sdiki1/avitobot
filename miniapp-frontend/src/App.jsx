import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  getAuthSession,
  getMiniappContent,
  getMonitorings,
  getPlans,
  getProfile,
  purchaseSubscription,
  resolveAuthToken,
  signInMiniApp,
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
  { id: 'standard', label: 'Стандартная', speed: '1.8 секунд' },
  { id: 'fast', label: 'Ускоренная', speed: '0.9 секунд' },
  { id: 'turbo', label: 'Скоростная', speed: '0.1 секунда' },
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
  webapp.expand?.()
  webapp.disableVerticalSwipes?.()
  try {
    const maybePromise = webapp.requestFullscreen?.()
    if (maybePromise && typeof maybePromise.catch === 'function') {
      maybePromise.catch(() => {})
    }
  } catch {
    // ignore: not supported in some Telegram clients
  }
  if (!webapp.initData || typeof webapp.initData !== 'string') return null
  return webapp.initData
}

function getAuthTokenFromQuery() {
  return new URLSearchParams(window.location.search).get('auth')
}

function formatRemaining(endsAt) {
  if (!endsAt) return 'без срока'
  const diffMs = new Date(endsAt).getTime() - Date.now()
  if (diffMs <= 0) return 'истекла'
  const hours = Math.floor(diffMs / (1000 * 60 * 60))
  if (hours < 48) return `${Math.max(1, hours)} ч.`
  return `${Math.ceil(hours / 24)} д.`
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
  const [selectedType, setSelectedType] = useState(TYPE_OPTIONS[0].id)
  const [selectedPeriod, setSelectedPeriod] = useState(7)
  const [useReferralBalance, setUseReferralBalance] = useState(false)
  const [buyDraft, setBuyDraft] = useState({ title: '', url: '' })

  const normalizedMonitorings = useMemo(() => {
    if (monitorings.length > 0) {
      return monitorings.map((item) => ({ ...item, uid: String(item.id) }))
    }

    if (profile?.subscription) {
      return [
        {
          uid: 'virtual-subscription',
          id: 'virtual-subscription',
          title: profile.subscription?.is_trial ? 'Тестовая подписка' : 'Подписка',
          url: '',
          bot: null,
          is_active: false,
          link_configured: false,
          virtual: true,
        },
      ]
    }

    return []
  }, [monitorings, profile])

  const selectedMonitoring = useMemo(
    () => normalizedMonitorings.find((item) => item.uid === selectedMonitoringId) || null,
    [normalizedMonitorings, selectedMonitoringId],
  )

  const periodOptions = useMemo(() => {
    const daysFromPlans = Array.from(new Set(plans.map((plan) => Number(plan.duration_days)).filter(Boolean))).sort(
      (a, b) => a - b,
    )
    if (daysFromPlans.length > 0) return daysFromPlans
    return [7, 15, 30]
  }, [plans])

  useEffect(() => {
    if (periodOptions.length > 0 && !periodOptions.includes(Number(selectedPeriod))) {
      setSelectedPeriod(periodOptions[0])
    }
  }, [periodOptions, selectedPeriod])

  const selectedPlan = useMemo(() => {
    const candidates = plans
      .filter((plan) => Number(plan.duration_days) === Number(selectedPeriod))
      .sort((a, b) => Number(a.price_rub) - Number(b.price_rub))
    if (candidates.length > 0) return candidates[0]
    return plans[0] || null
  }, [plans, selectedPeriod])

  const referralBalance = profile?.user?.referral_balance_rub ?? 0
  const totalPrice = Math.max(0, Number(selectedPlan?.price_rub || 0) - (useReferralBalance ? referralBalance : 0))

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
        [uid]: { ...DEFAULT_PARAM_FLAGS },
      }
    })
  }

  const openSubscriptionDetails = (monitoring) => {
    ensureDraft(monitoring)
    setSelectedMonitoringId(String(monitoring.uid))
    setSubscriptionView(SUBSCRIPTION_VIEW.detail)
  }

  const openBuyScreen = () => {
    if (selectedMonitoring) {
      ensureDraft(selectedMonitoring)
      const draft = drafts[selectedMonitoring.uid] || {
        title: selectedMonitoring.title || '',
        url: selectedMonitoring.url || '',
      }
      setBuyDraft({ title: draft.title || '', url: draft.url || '' })
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
      setSubscriptionView(selectedMonitoringId ? SUBSCRIPTION_VIEW.detail : SUBSCRIPTION_VIEW.home)
      return
    }

    window.Telegram?.WebApp?.close?.()
  }, [selectedMonitoringId, subscriptionView, tab])

  const onPurchase = async () => {
    if (!telegramId || !selectedPlan || purchaseBusy) return
    try {
      setPurchaseBusy(true)
      const result = await purchaseSubscription({
        telegram_id: Number(telegramId),
        plan_id: Number(selectedPlan.id),
      })

      await loadData(telegramId)
      if (result?.is_trial) {
        setStatusMessage(`Активирован пробный период: ${selectedPlan.name}`)
      } else {
        setStatusMessage(`Подписка активирована: ${selectedPlan.name}`)
      }
      setSubscriptionView(selectedMonitoring ? SUBSCRIPTION_VIEW.detail : SUBSCRIPTION_VIEW.home)
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.message || 'Ошибка покупки подписки'
      setStatusMessage(`Ошибка: ${detail}`)
    } finally {
      setPurchaseBusy(false)
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
    ? paramFlags[selectedMonitoring.uid] || DEFAULT_PARAM_FLAGS
    : DEFAULT_PARAM_FLAGS

  const detailBotLink = selectedMonitoring ? buildSubscriptionBotLink(selectedMonitoring.bot) : null

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
                  <div className="empty-card">У вас пока нет подписок. Нажмите «Купить подписку».</div>
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
                      <strong>{monitoring.title || 'Тестовая подписка'}</strong>
                      <span>
                        {(profile?.subscription?.plan_name || 'Стандарт')} - {formatRemaining(profile?.subscription?.ends_at)}
                      </span>
                    </span>

                    <span className="subscription-chevron">
                      <IconChevron />
                    </span>
                  </button>
                ))}
              </div>

              <button type="button" className="primary-btn purchase-bottom-btn" onClick={openBuyScreen}>
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
                    onChange={(event) => updateSelectedDraft({ title: event.target.value })}
                  />

                  <input
                    type="text"
                    className="dark-input"
                    placeholder="Укажите ссылку на объявления"
                    value={detailDraft.url}
                    onChange={(event) => updateSelectedDraft({ url: event.target.value })}
                  />

                  <p className="hint-text">Ссылка на объявления — это поисковая ссылка, которая выводит все объявления при поиске.</p>

                  <button type="button" className="primary-btn" onClick={openBuyScreen}>
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

                  <p className="hint-text">
                    Перед первым запуском не забудь{' '}
                    <a href={detailBotLink || '#'} target="_blank" rel="noreferrer">
                      запустить бота отправителя
                    </a>
                  </p>

                  <button
                    type="button"
                    className="primary-btn"
                    onClick={() => {
                      if (!detailBotLink) {
                        setStatusMessage('Для этой подписки бот пока не назначен')
                        return
                      }
                      openExternal(detailBotLink)
                    }}
                  >
                    Запустить поиск
                  </button>

                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => {
                      if (!detailBotLink) {
                        setStatusMessage('Для этой подписки бот пока не назначен')
                        return
                      }
                      openExternal(detailBotLink)
                    }}
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
                    onClick={() => setSelectedType(option.id)}
                  >
                    <span className="choice-dot" />
                    <span className="choice-main">{option.label}</span>
                    <span className="choice-meta">({option.speed})</span>
                  </button>
                ))}
              </div>

              <h2 className="section-title">Период подписки</h2>
              <div className="choices-list">
                {periodOptions.map((days) => (
                  <button
                    key={days}
                    type="button"
                    className={`choice-row ${Number(selectedPeriod) === Number(days) ? 'active' : ''}`}
                    onClick={() => setSelectedPeriod(Number(days))}
                  >
                    <span className="choice-dot" />
                    <span className="choice-main">{days} дней</span>
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

              <button type="button" className="primary-btn" onClick={onPurchase} disabled={!selectedPlan || purchaseBusy}>
                {purchaseBusy ? 'Покупка...' : 'Оплатить через СБП 🔷'}
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

                <div className="profile-row">
                  <span>Текущая подписка</span>
                  <div>
                    <strong>
                      {profile?.subscription
                        ? `${profile.subscription.plan_name}${profile.subscription.is_trial ? ' (тест)' : ''} до ${formatDateTime(profile.subscription.ends_at)}`
                        : 'Нет активной'}
                    </strong>
                  </div>
                </div>

                <div className="profile-row">
                  <span>Назначенный бот</span>
                  <div>
                    <strong>{selectedMonitoring ? botShortName(selectedMonitoring.bot) : '—'}</strong>
                  </div>
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
