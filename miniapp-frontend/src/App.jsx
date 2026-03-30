import { useEffect, useMemo, useState } from 'react'
import {
  authTelegramUser,
  createMonitoring,
  deleteMonitoring,
  getMonitoringItems,
  getMonitorings,
  getNotifications,
  getPlans,
  getProfile,
} from './api'

function getTelegramUser() {
  const tg = window.Telegram?.WebApp
  if (!tg) return null
  tg.ready()
  return tg.initDataUnsafe?.user || null
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  return date.toLocaleString('ru-RU')
}

function isSubscriptionExpiringSoon(profile) {
  if (!profile?.subscription?.ends_at) return false
  const diffDays = (new Date(profile.subscription.ends_at) - new Date()) / (1000 * 60 * 60 * 24)
  return diffDays >= 0 && diffDays <= 5
}

function isSubscriptionInactive(profile) {
  return !profile?.subscription
}

function getStatusPillClass(loading, statusText) {
  if (loading) return 'status-pill loading'
  if (statusText.startsWith('Ошибка')) return 'status-pill error'
  return 'status-pill'
}

export default function App() {
  const [telegramId, setTelegramId] = useState(null)
  const [manualId, setManualId] = useState('')
  const [statusText, setStatusText] = useState('Инициализация miniapp...')
  const [loading, setLoading] = useState(true)

  const [profile, setProfile] = useState(null)
  const [plans, setPlans] = useState([])
  const [monitorings, setMonitorings] = useState([])
  const [notifications, setNotifications] = useState([])

  const [selectedMonitoringId, setSelectedMonitoringId] = useState(null)
  const [items, setItems] = useState([])

  const [form, setForm] = useState({
    url: '',
    title: '',
    keywords_white: '',
    keywords_black: '',
    min_price: '',
    max_price: '',
    geo: '',
  })

  const activeMonitoring = useMemo(
    () => monitorings.find((m) => m.id === selectedMonitoringId) || null,
    [monitorings, selectedMonitoringId],
  )

  const resolveTelegramId = () => {
    const tgUser = getTelegramUser()
    if (tgUser?.id) return Number(tgUser.id)

    const query = new URLSearchParams(window.location.search)
    const queryId = query.get('tg_id')
    if (queryId) return Number(queryId)

    return null
  }

  const refreshData = async (tgId) => {
    const [profileData, plansData, monitoringsData, notificationsData] = await Promise.all([
      getProfile(tgId),
      getPlans(),
      getMonitorings(tgId),
      getNotifications(tgId),
    ])

    setProfile(profileData)
    setPlans(plansData)
    setMonitorings(monitoringsData)
    setNotifications(notificationsData)

    if (!selectedMonitoringId && monitoringsData.length > 0) {
      setSelectedMonitoringId(monitoringsData[0].id)
    }
  }

  useEffect(() => {
    const init = async () => {
      try {
        const resolvedId = resolveTelegramId()
        if (!resolvedId) {
          setStatusText('Не удалось определить Telegram ID. Введите вручную для локального теста.')
          setLoading(false)
          return
        }

        setTelegramId(resolvedId)
        await authTelegramUser({ telegram_id: resolvedId })
        await refreshData(resolvedId)
        setStatusText('Система готова: мониторинг Avito активен')
      } catch (error) {
        const message =
          error?.response?.data?.detail || error?.message || 'Ошибка загрузки miniapp данных'
        setStatusText(`Ошибка: ${message}`)
      } finally {
        setLoading(false)
      }
    }
    init()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!telegramId || !selectedMonitoringId) return

    getMonitoringItems(telegramId, selectedMonitoringId)
      .then(setItems)
      .catch((error) => {
        const message = error?.response?.data?.detail || error?.message || 'Не удалось загрузить объявления'
        setStatusText(`Ошибка: ${message}`)
      })
  }, [telegramId, selectedMonitoringId])

  const onSubmitManualId = async () => {
    const parsed = Number(manualId)
    if (!parsed) {
      setStatusText('Введите корректный Telegram ID')
      return
    }

    try {
      setLoading(true)
      setTelegramId(parsed)
      await authTelegramUser({ telegram_id: parsed })
      await refreshData(parsed)
      setStatusText('Подключение по Telegram ID выполнено')
    } catch (error) {
      const message = error?.response?.data?.detail || error?.message || 'Ошибка подключения'
      setStatusText(`Ошибка: ${message}`)
    } finally {
      setLoading(false)
    }
  }

  const onCreateMonitoring = async (event) => {
    event.preventDefault()
    if (!telegramId) return

    try {
      await createMonitoring({
        telegram_id: telegramId,
        url: form.url,
        title: form.title || null,
        keywords_white: form.keywords_white
          .split(',')
          .map((v) => v.trim())
          .filter(Boolean),
        keywords_black: form.keywords_black
          .split(',')
          .map((v) => v.trim())
          .filter(Boolean),
        min_price: form.min_price ? Number(form.min_price) : null,
        max_price: form.max_price ? Number(form.max_price) : null,
        geo: form.geo || null,
      })

      setForm({
        url: '',
        title: '',
        keywords_white: '',
        keywords_black: '',
        min_price: '',
        max_price: '',
        geo: '',
      })
      await refreshData(telegramId)
      setStatusText('Ссылка добавлена. Парсер начнет цикл на следующей итерации.')
    } catch (error) {
      const message = error?.response?.data?.detail || error?.message || 'Ошибка добавления ссылки'
      setStatusText(`Ошибка: ${message}`)
    }
  }

  const onDeleteMonitoring = async (monitoringId) => {
    if (!telegramId) return
    try {
      await deleteMonitoring(telegramId, monitoringId)
      await refreshData(telegramId)
      if (selectedMonitoringId === monitoringId) {
        setSelectedMonitoringId(null)
        setItems([])
      }
      setStatusText('Мониторинг удален')
    } catch (error) {
      const message = error?.response?.data?.detail || error?.message || 'Ошибка удаления'
      setStatusText(`Ошибка: ${message}`)
    }
  }

  return (
    <div className="page">
      <div className="aurora" aria-hidden="true" />

      {/* Hero */}
      <header className="hero card">
        <div className="hero-top">
          <div>
            <p className="eyebrow">Telegram MiniApp</p>
            <div className="hero-title-wrap">
              <h1>Avito Monitor</h1>
            </div>
            <p className="subtitle" style={{ marginTop: 10 }}>
              Быстрый парсинг новых объявлений Avito с фильтрами.
            </p>
          </div>
          <div className={getStatusPillClass(loading, statusText)}>
            {loading ? 'Загрузка...' : statusText}
          </div>
        </div>
      </header>

      {/* Subscription banners */}
      {!loading && telegramId && isSubscriptionInactive(profile) && (
        <div className="sub-banner inactive card">
          <div className="sub-banner-text">
            <strong>Подписка не активна</strong>
            <small>Купите тариф ниже, чтобы запустить мониторинг</small>
          </div>
        </div>
      )}
      {!loading && telegramId && !isSubscriptionInactive(profile) && isSubscriptionExpiringSoon(profile) && (
        <div className="sub-banner warn card">
          <div className="sub-banner-text">
            <strong>Подписка истекает скоро</strong>
            <small>до {formatDate(profile.subscription.ends_at)}</small>
          </div>
        </div>
      )}

      {/* Manual ID entry */}
      {!telegramId && (
        <section className="card">
          <h2>Локальный вход</h2>
          <p className="hint">MiniApp не получил Telegram ID автоматически. Введите ID для теста.</p>
          <div className="inline-form">
            <input
              value={manualId}
              onChange={(e) => setManualId(e.target.value)}
              placeholder="Telegram ID"
            />
            <button onClick={onSubmitManualId}>Подключить</button>
          </div>
        </section>
      )}

      {/* Stats */}
      <section className="grid stats-grid">
        <article className="card metric">
          <div className="metric-icon">🔗</div>
          <span>Активных ссылок</span>
          {loading
            ? <div className="skeleton skeleton-text wide" style={{ height: 28, marginBottom: 0 }} />
            : <strong>{profile?.active_monitorings ?? 0}</strong>
          }
        </article>
        <article className="card metric">
          <div className="metric-icon">🔔</div>
          <span>Уведомлений</span>
          {loading
            ? <div className="skeleton skeleton-text wide" style={{ height: 28, marginBottom: 0 }} />
            : <strong>{notifications.length}</strong>
          }
        </article>
        <article className="card metric">
          <div className="metric-icon">✦</div>
          <span>Подписка</span>
          {loading
            ? <div className="skeleton skeleton-text wide" style={{ height: 28, marginBottom: 0 }} />
            : <strong style={{ fontSize: 14, fontWeight: 700 }}>
                {profile?.subscription
                  ? `до ${formatDate(profile.subscription.ends_at)}`
                  : 'Нет'}
              </strong>
          }
        </article>
      </section>

      {/* Add monitoring + Plans */}
      <section className="grid two-columns">
        <article className="card">
          <h2>Добавить ссылку</h2>
          <form className="stack" onSubmit={onCreateMonitoring}>
            <label className="form-label">
              URL Avito
              <input
                required
                value={form.url}
                onChange={(e) => setForm((prev) => ({ ...prev, url: e.target.value }))}
                placeholder="https://www.avito.ru/..."
              />
            </label>
            <label className="form-label">
              Название (опционально)
              <input
                value={form.title}
                onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
                placeholder="Например: iPhone 15"
              />
            </label>
            <div className="inline-form">
              <label className="form-label">
                Белые слова
                <input
                  value={form.keywords_white}
                  onChange={(e) => setForm((prev) => ({ ...prev, keywords_white: e.target.value }))}
                  placeholder="слово1, слово2"
                />
              </label>
              <label className="form-label">
                Черные слова
                <input
                  value={form.keywords_black}
                  onChange={(e) => setForm((prev) => ({ ...prev, keywords_black: e.target.value }))}
                  placeholder="слово1, слово2"
                />
              </label>
            </div>
            <div className="inline-form">
              <label className="form-label">
                Мин. цена
                <input
                  type="number"
                  value={form.min_price}
                  onChange={(e) => setForm((prev) => ({ ...prev, min_price: e.target.value }))}
                  placeholder="0"
                />
              </label>
              <label className="form-label">
                Макс. цена
                <input
                  type="number"
                  value={form.max_price}
                  onChange={(e) => setForm((prev) => ({ ...prev, max_price: e.target.value }))}
                  placeholder="∞"
                />
              </label>
            </div>
            <label className="form-label">
              Город / регион
              <input
                value={form.geo}
                onChange={(e) => setForm((prev) => ({ ...prev, geo: e.target.value }))}
                placeholder="Москва"
              />
            </label>
            <button type="submit">Запустить мониторинг</button>
          </form>
        </article>

        <article className="card">
          <h2>Тарифные планы</h2>
          <div className="plans-list">
            {loading && (
              <>
                <div className="plan-item">
                  <div className="skeleton skeleton-text wide" style={{ height: 16, margin: 0 }} />
                </div>
                <div className="plan-item">
                  <div className="skeleton skeleton-text wide" style={{ height: 16, margin: 0 }} />
                </div>
              </>
            )}
            {plans.map((plan) => (
              <div key={plan.id} className="plan-item">
                <div>
                  <strong>{plan.name}</strong>
                  <p>{plan.links_limit} ссылок · {plan.duration_days} дней</p>
                </div>
                <span className="plan-price">{plan.price_rub} ₽</span>
              </div>
            ))}
          </div>
          <p className="hint" style={{ marginTop: 12 }}>
            Для покупки обратитесь к боту или администратору.
          </p>
        </article>
      </section>

      {/* Monitorings + Ads */}
      <section className="grid two-columns">
        <article className="card">
          <h2>Мои мониторинги</h2>
          <div className="monitoring-list">
            {loading && (
              <>
                {[1, 2].map((i) => (
                  <div key={i} className="monitoring-item" style={{ pointerEvents: 'none' }}>
                    <div style={{ width: '100%' }}>
                      <div className="skeleton skeleton-text wide" />
                      <div className="skeleton skeleton-text mid" />
                    </div>
                  </div>
                ))}
              </>
            )}
            {!loading && monitorings.length === 0 && (
              <div className="empty-state">
                <span className="empty-icon">🔍</span>
                <p>Пока нет активных мониторингов.<br />Добавьте первую ссылку!</p>
              </div>
            )}
            {monitorings.map((m) => (
              <button
                key={m.id}
                className={`monitoring-item ${selectedMonitoringId === m.id ? 'active' : ''}`}
                onClick={() => setSelectedMonitoringId(m.id)}
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="monitoring-header">
                    <span className={`status-dot ${selectedMonitoringId === m.id ? 'green' : 'gray'}`} />
                    <strong style={{ fontSize: 14 }}>{m.title || `Ссылка #${m.id}`}</strong>
                  </div>
                  <p>{m.url}</p>
                  <small>Проверено: {formatDate(m.last_checked_at)}</small>
                </div>
                <button
                  className="monitoring-delete"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDeleteMonitoring(m.id)
                  }}
                >
                  Удалить
                </button>
              </button>
            ))}
          </div>
        </article>

        <article className="card">
          <h2>
            Объявления
            {activeMonitoring && (
              <span style={{ fontWeight: 500, color: 'var(--muted)', fontSize: 13, marginLeft: 6 }}>
                — {activeMonitoring.title || `#${activeMonitoring.id}`}
              </span>
            )}
          </h2>
          <div className="ads-list">
            {loading && (
              <>
                {[1, 2, 3].map((i) => (
                  <div key={i} className="ad-item" style={{ pointerEvents: 'none' }}>
                    <div className="skeleton skeleton-text wide" />
                    <div className="skeleton skeleton-text short" style={{ height: 20 }} />
                    <div className="skeleton skeleton-text mid" />
                  </div>
                ))}
              </>
            )}
            {!loading && items.length === 0 && (
              <div className="empty-state">
                <span className="empty-icon">📭</span>
                <p>Новых объявлений нет.<br />Выберите мониторинг или дождитесь следующего цикла.</p>
              </div>
            )}
            {items.map((item) => (
              <a href={item.url} key={item.id} target="_blank" rel="noreferrer" className="ad-item">
                <span className="ad-title">{item.title}</span>
                <span className="ad-price">
                  {item.price_rub ? `${item.price_rub.toLocaleString('ru-RU')} ₽` : 'Цена не указана'}
                </span>
                <div className="ad-footer">
                  <span className="ad-location">{item.location || 'Локация не указана'}</span>
                  <span className="ad-time">Найдено: {formatDate(item.first_seen_at)}</span>
                </div>
              </a>
            ))}
          </div>
        </article>
      </section>
    </div>
  )
}
