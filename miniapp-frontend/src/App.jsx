import { useEffect, useMemo, useState } from 'react'
import {
  authTelegramUser,
  getMonitorings,
  getPlans,
  getProfile,
  purchaseMonitoring,
  purchaseSubscription,
} from './api'

const TABS = {
  info: 'info',
  subscriptions: 'subscriptions',
  profile: 'profile',
}

function telegramUser() {
  const tg = window.Telegram?.WebApp
  if (!tg) return null
  tg.ready()
  tg.expand?.()
  return tg.initDataUnsafe?.user || null
}

function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU')
}

function formatUsername(bot) {
  if (!bot?.bot_username) return null
  return bot.bot_username.startsWith('@') ? bot.bot_username : `@${bot.bot_username}`
}

function statusClass(monitoring) {
  if (!monitoring.link_configured) return 'badge neutral'
  return monitoring.is_active ? 'badge active' : 'badge stopped'
}

function monitoringStatusText(monitoring) {
  if (!monitoring.link_configured) return 'link required'
  return monitoring.is_active ? 'running' : 'stopped'
}

export default function App() {
  const [tab, setTab] = useState(TABS.subscriptions)
  const [telegramId, setTelegramId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [statusMessage, setStatusMessage] = useState('Инициализация...')
  const [plans, setPlans] = useState([])
  const [profile, setProfile] = useState(null)
  const [monitorings, setMonitorings] = useState([])
  const [selectedPlanId, setSelectedPlanId] = useState('')
  const [purchaseBusy, setPurchaseBusy] = useState(false)
  const [monitoringBusy, setMonitoringBusy] = useState(false)

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
        const user = telegramUser()
        if (!user?.id) {
          setStatusMessage('Откройте miniapp через Telegram-бота')
          return
        }
        const tgId = Number(user.id)
        setTelegramId(tgId)

        const fullName = [user.first_name, user.last_name].filter(Boolean).join(' ') || null
        await authTelegramUser({
          telegram_id: tgId,
          username: user.username || null,
          full_name: fullName,
        })
        await loadData(tgId)
        setStatusMessage('Подключено')
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
      await purchaseSubscription({
        telegram_id: telegramId,
        plan_id: Number(selectedPlanId),
      })
      await loadData(telegramId)
      setStatusMessage(`Подписка активирована: ${activePlan?.name || 'тариф'}`)
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.message || 'Ошибка покупки подписки'
      setStatusMessage(`Ошибка: ${detail}`)
    } finally {
      setPurchaseBusy(false)
    }
  }

  const onBuyMonitoring = async () => {
    if (!telegramId || monitoringBusy) return
    try {
      setMonitoringBusy(true)
      const monitoring = await purchaseMonitoring({
        telegram_id: telegramId,
      })
      await loadData(telegramId)
      if (monitoring?.bot?.bot_link) {
        setStatusMessage(`Мониторинг куплен. Откройте ${monitoring.bot.bot_link}`)
      } else {
        setStatusMessage('Мониторинг куплен. Бот привязан, ссылка появится после синхронизации.')
      }
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.message || 'Ошибка покупки мониторинга'
      setStatusMessage(`Ошибка: ${detail}`)
    } finally {
      setMonitoringBusy(false)
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
        <header className="hero">
          <div>
            <p className="eyebrow">Avito Monitor</p>
            <h1>MiniApp Control</h1>
            <p className="sub">
              Управление подпиской и выдачей ботов. Вся работа по ссылке ведётся внутри назначенного бота.
            </p>
          </div>
          <div className={`status ${statusMessage.startsWith('Ошибка') ? 'error' : ''}`}>
            {loading ? 'Загрузка...' : statusMessage}
          </div>
        </header>

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
            <article className="card">
              <h2>Активные боты</h2>
              <p className="muted">
                На каждый купленный мониторинг назначается отдельный бот для вашего аккаунта.
              </p>
              <div className="monitorings">
                {monitorings.length === 0 && (
                  <div className="empty">У вас пока нет купленных мониторингов.</div>
                )}
                {monitorings.map((monitoring) => (
                  <div className="monitoring-item" key={monitoring.id}>
                    <div>
                      <strong>{monitoring.title || `Мониторинг #${monitoring.id}`}</strong>
                      <p>{monitoring.url}</p>
                      <p>
                        Бот: {monitoring.bot?.name || 'не назначен'}
                        {formatUsername(monitoring.bot) ? ` (${formatUsername(monitoring.bot)})` : ''}
                      </p>
                    </div>
                    <div className="monitoring-side">
                      <span className={statusClass(monitoring)}>{monitoringStatusText(monitoring)}</span>
                      {monitoring.bot?.bot_link && (
                        <a href={monitoring.bot.bot_link} target="_blank" rel="noreferrer" className="mini-link">
                          Открыть бота
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </article>

            <article className="card">
              <h2>Подписки</h2>
              <p className="muted">
                Активная подписка:{' '}
                {profile?.subscription
                  ? `${profile.subscription.plan_name} до ${formatDate(profile.subscription.ends_at)}`
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

            <article className="card">
              <h2>Купить мониторинг</h2>
              <p className="muted">
                После покупки вы получите бота под новый мониторинг. Управление ссылкой/запуском выполняется в самом боте.
              </p>
              <button type="button" onClick={onBuyMonitoring} disabled={monitoringBusy}>
                {monitoringBusy ? 'Оформление...' : 'Купить мониторинг'}
              </button>
            </article>
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
                      className="text-btn"
                      onClick={() =>
                        copyText(String(profile?.user?.telegram_id || telegramId || ''), 'Telegram ID скопирован')
                      }
                    >
                      Копировать
                    </button>
                  </div>
                </div>
                <div className="profile-row">
                  <span>Реферальная ссылка</span>
                  <div>
                    <strong>{profile?.referral_link || profile?.user?.referral_code || '—'}</strong>
                    <button
                      type="button"
                      className="text-btn"
                      onClick={() =>
                        copyText(
                          profile?.referral_link || profile?.user?.referral_code || '',
                          'Реферальная ссылка скопирована',
                        )
                      }
                    >
                      Копировать
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
          onClick={() => setTab(TABS.subscriptions)}
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
