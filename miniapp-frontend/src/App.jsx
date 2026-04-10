import { useEffect, useMemo, useState } from 'react'
import {
  authTelegramUser,
  getMonitorings,
  getPlans,
  getProfile,
  purchaseSubscription,
  resolveAuthToken,
} from './api'

const TABS = {
  info: 'info',
  subscriptions: 'subscriptions',
  profile: 'profile',
}

const SUBSCRIPTION_VIEW = {
  home: 'home',
  buy: 'buy',
}

function telegramUser() {
  const tg = window.Telegram?.WebApp
  if (!tg) return null
  tg.ready()
  tg.expand?.()
  return tg.initDataUnsafe?.user || null
}

function authTokenFromQuery() {
  return new URLSearchParams(window.location.search).get('auth')
}

function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU')
}

function formatBotLabel(bot) {
  if (!bot) return 'Бот не назначен'
  const username = bot.bot_username
    ? (bot.bot_username.startsWith('@') ? bot.bot_username : `@${bot.bot_username}`)
    : null
  if (!username) return bot.name
  return `${bot.name} (${username})`
}

function buildSubscriptionBotLink(bot) {
  const base = bot?.bot_link
  if (!base) return null
  const joiner = base.includes('?') ? '&' : '?'
  return `${base}${joiner}start=subscription`
}

function CopyIcon() {
  return (
    <svg className="copy-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M8 8h10v12H8zM6 4h10v2H8v10H6z"
        fill="currentColor"
      />
    </svg>
  )
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
  const [selectedPlanId, setSelectedPlanId] = useState('')
  const [purchaseBusy, setPurchaseBusy] = useState(false)

  const activePlan = useMemo(
    () => plans.find((plan) => plan.id === Number(selectedPlanId)) || null,
    [plans, selectedPlanId],
  )

  const loadData = async (tgId) => {
    const [profileData, plansData, monitoringsData] = await Promise.all([
      getProfile(tgId),
      getPlans(),
      getMonitorings(tgId),
    ])
    setProfile(profileData)
    setPlans(plansData)
    setMonitorings(monitoringsData)
    if (!selectedPlanId && plansData.length > 0) {
      setSelectedPlanId(String(plansData[0].id))
    }
  }

  useEffect(() => {
    const init = async () => {
      try {
        let resolvedTelegramId = null
        let authResolveFailed = false

        const authToken = authTokenFromQuery()
        if (authToken) {
          try {
            const resolved = await resolveAuthToken(authToken)
            resolvedTelegramId = Number(resolved.telegram_id)
          } catch {
            authResolveFailed = true
          }
        }

        const user = telegramUser()
        if (!resolvedTelegramId && user?.id) {
          resolvedTelegramId = Number(user.id)
          const fullName = [user.first_name, user.last_name].filter(Boolean).join(' ') || null
          await authTelegramUser({
            telegram_id: resolvedTelegramId,
            username: user.username || null,
            full_name: fullName,
          })
        }

        if (!resolvedTelegramId) {
          setStatusMessage(authResolveFailed ? 'Ошибка: ссылка авторизации недействительна' : 'Ошибка: нет данных авторизации')
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

  const onBuySubscription = async () => {
    if (!telegramId || !selectedPlanId || purchaseBusy) return
    try {
      setPurchaseBusy(true)
      const purchaseResult = await purchaseSubscription({
        telegram_id: telegramId,
        plan_id: Number(selectedPlanId),
      })
      await loadData(telegramId)
      if (purchaseResult?.is_trial) {
        setStatusMessage(`Активирован пробный период: ${activePlan?.name || 'тариф'}`)
      } else {
        setStatusMessage(`Подписка активирована: ${activePlan?.name || 'тариф'}`)
      }
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.message || 'Ошибка покупки подписки'
      setStatusMessage(`Ошибка: ${detail}`)
    } finally {
      setPurchaseBusy(false)
    }
  }

  const copyText = async (value, okMessage) => {
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      setStatusMessage(okMessage)
    } catch (error) {
      setStatusMessage('Не удалось скопировать')
    }
  }

  return (
    <div className="app-shell">
      <div className="bg-layer" aria-hidden="true" />
      <main className="app-main">
        {!loading && statusMessage && (
          <section className="card">
            <div className={`status ${statusMessage.startsWith('Ошибка') ? 'error' : ''}`}>
              {statusMessage}
            </div>
          </section>
        )}

        {!loading && tab === TABS.info && (
          <section className="stack">
            <article className="card">
              <h2>Информация</h2>
              <p className="muted">Основные ссылки сервиса.</p>
              <div className="links">
                <a href="https://t.me/your_support" target="_blank" rel="noreferrer">Поддержка</a>
                <a href="https://t.me/your_faq" target="_blank" rel="noreferrer">Частые вопросы</a>
                <a href="https://t.me/your_news" target="_blank" rel="noreferrer">Новостной канал</a>
                <a href="https://t.me/your_terms" target="_blank" rel="noreferrer">Пользовательское соглашение</a>
                <a href="https://t.me/your_privacy" target="_blank" rel="noreferrer">Политика конфиденциальности</a>
              </div>
            </article>
          </section>
        )}

        {!loading && tab === TABS.subscriptions && (
          <section className="stack">
            {subscriptionView === SUBSCRIPTION_VIEW.home && (
              <article className="card subscription-home">
                <h2>Подписки</h2>
                <p className="muted">
                  Текущая подписка:{' '}
                  {profile?.subscription
                    ? `${profile.subscription.plan_name}${profile.subscription.is_trial ? ' (пробный период)' : ''} до ${formatDate(profile.subscription.ends_at)}`
                    : 'нет'}
                </p>
                <div className="monitorings">
                  {monitorings.length === 0 && (
                    <div className="empty">У вас пока нет активных подписок на мониторинг.</div>
                  )}
                  {monitorings.map((monitoring) => {
                    const subscriptionLink = buildSubscriptionBotLink(monitoring.bot)
                    return (
                      <div className="monitoring-item" key={monitoring.id}>
                        <div>
                          <strong>{monitoring.title || `Мониторинг #${monitoring.id}`}</strong>
                          <p>{monitoring.url}</p>
                          {subscriptionLink ? (
                            <a
                              href={subscriptionLink}
                              target="_blank"
                              rel="noreferrer"
                              className="bot-link"
                            >
                              {formatBotLabel(monitoring.bot)}
                            </a>
                          ) : (
                            <p>{formatBotLabel(monitoring.bot)}</p>
                          )}
                        </div>
                        {subscriptionLink && (
                          <a
                            href={subscriptionLink}
                            target="_blank"
                            rel="noreferrer"
                            className="mini-link"
                          >
                            Открыть подписку
                          </a>
                        )}
                      </div>
                    )
                  })}
                </div>
                <button
                  type="button"
                  className="subscription-primary-btn"
                  onClick={() => setSubscriptionView(SUBSCRIPTION_VIEW.buy)}
                >
                  Купить подписку
                </button>
              </article>
            )}

            {subscriptionView === SUBSCRIPTION_VIEW.buy && (
              <>
                <article className="card">
                  <div className="section-head">
                    <button
                      type="button"
                      className="section-back-btn"
                      onClick={() => setSubscriptionView(SUBSCRIPTION_VIEW.home)}
                    >
                      Назад
                    </button>
                    <h2>Выбор тарифа</h2>
                  </div>
                  <p className="muted">
                    Активная подписка:{' '}
                    {profile?.subscription
                      ? `${profile.subscription.plan_name}${profile.subscription.is_trial ? ' (пробный период)' : ''} до ${formatDate(profile.subscription.ends_at)}`
                      : 'нет'}
                  </p>
                  <div className="buy-row">
                    <select
                      value={selectedPlanId}
                      onChange={(event) => setSelectedPlanId(event.target.value)}
                    >
                      {plans.map((plan) => (
                        <option key={plan.id} value={plan.id}>
                          {plan.name} • {plan.price_rub} ₽
                        </option>
                      ))}
                    </select>
                    <button type="button" onClick={onBuySubscription} disabled={!selectedPlanId || purchaseBusy}>
                      {purchaseBusy ? 'Покупка...' : 'Купить подписку'}
                    </button>
                  </div>
                </article>

                <article className="card">
                  <h2>Тарифы</h2>
                  <div className="plans-list">
                    {plans.map((plan) => (
                      <div key={plan.id} className="plan">
                        <strong>{plan.name}</strong>
                        <span>{plan.links_limit} мониторингов • {plan.duration_days} дней</span>
                        <span>{plan.price_rub} ₽</span>
                      </div>
                    ))}
                  </div>
                </article>
              </>
            )}
          </section>
        )}

        {!loading && tab === TABS.profile && (
          <section className="stack">
            <article className="card">
              <h2>Профиль</h2>
              <div className="profile-list">
                <div className="profile-row">
                  <span>Telegram ID</span>
                  <div>
                    <strong>{profile?.user?.telegram_id || telegramId || '—'}</strong>
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label="Скопировать Telegram ID"
                      title="Скопировать Telegram ID"
                      onClick={() =>
                        copyText(String(profile?.user?.telegram_id || telegramId || ''), 'Telegram ID скопирован')
                      }
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
                      className="icon-btn"
                      aria-label="Скопировать реферальную ссылку"
                      title="Скопировать реферальную ссылку"
                      onClick={() =>
                        copyText(
                          profile?.referral_link || profile?.user?.referral_code || '',
                          'Реферальная ссылка скопирована',
                        )
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
              </div>
            </article>
          </section>
        )}
      </main>

      <nav className="bottom-nav">
        <button
          type="button"
          className={tab === TABS.info ? 'tab active' : 'tab'}
          onClick={() => setTab(TABS.info)}
        >
          Информация
        </button>
        <button
          type="button"
          className={tab === TABS.subscriptions ? 'tab active' : 'tab'}
          onClick={() => {
            setTab(TABS.subscriptions)
            setSubscriptionView(SUBSCRIPTION_VIEW.home)
          }}
        >
          Подписки
        </button>
        <button
          type="button"
          className={tab === TABS.profile ? 'tab active' : 'tab'}
          onClick={() => setTab(TABS.profile)}
        >
          Профиль
        </button>
      </nav>
    </div>
  )
}
