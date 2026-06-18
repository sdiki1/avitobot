export const TABS = {
  info: 'info',
  subscriptions: 'subscriptions',
  profile: 'profile',
}

export const SUBSCRIPTION_VIEW = {
  home: 'home',
  detail: 'detail',
  buy: 'buy',
}

export const TYPE_OPTIONS = [
  { id: 'standard', label: 'Обычная', hint: 'стандартный режим' },
  { id: 'speed', label: 'Ускоренная', hint: 'приоритетный режим' },
]

export const PARAM_OPTIONS = [
  { key: 'photo', label: 'Фотография' },
  { key: 'description', label: 'Описание' },
  { key: 'seller', label: 'Информация о продавце' },
  { key: 'price_drop', label: 'Снижение цены' },
]

export const DEFAULT_PARAM_FLAGS = {
  photo: true,
  description: true,
  seller: true,
  price_drop: true,
}

export const DEFAULT_MINIAPP_CONTENT = {
  support_title: 'Поддержка',
  support_url: 'https://t.me/your_support',
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
    { key: 'news', title: 'Новостной канал', url: 'https://t.me/your_news' },
    { key: 'terms', title: 'Пользовательское соглашение', url: 'https://t.me/your_terms' },
    { key: 'privacy', title: 'Политика конфиденциальности', url: 'https://t.me/your_privacy' },
  ],
}

const MOSCOW_TZ = 'Europe/Moscow'

export function formatDateTime(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', { timeZone: MOSCOW_TZ })
}

export function buildSubscriptionBotLink(bot) {
  const base = bot?.bot_link
  if (!base) return null
  const separator = base.includes('?') ? '&' : '?'
  return `${base}${separator}start=subscription`
}

export function openExternal(url) {
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

export function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 8h10v12H8zM6 4h10v2H8v10H6z" fill="currentColor" />
    </svg>
  )
}

export function IconHome() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 10.7L12 4l8 6.7V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-9.3z" fill="currentColor" />
    </svg>
  )
}

export function IconTicket() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7a3 3 0 1 0 0 6v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4a3 3 0 1 0 0-6V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v0z" fill="currentColor" />
      <path d="M12 8v8" stroke="#150f24" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

export function IconProfile() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="8" r="4" fill="currentColor" />
      <path d="M4 20c0-3.5 3.6-6 8-6s8 2.5 8 6" fill="currentColor" />
    </svg>
  )
}

export function IconChevron() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 5l7 7-7 7" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function LoadingBlock() {
  return (
    <section className="screen-block">
      <div className="empty-card">Загрузка...</div>
    </section>
  )
}

export function botShortName(bot) {
  if (bot?.bot_username) return `@${String(bot.bot_username).replace(/^@/, '')}`
  return bot?.name || 'Бот не назначен'
}

export function isCurrentSubscription(subscription) {
  const status = String(subscription?.status || '').toLowerCase()
  if (status !== 'active') return false
  if (!subscription?.ends_at) return true
  const endsAtTs = new Date(subscription.ends_at).getTime()
  if (Number.isNaN(endsAtTs)) return true
  return endsAtTs > Date.now()
}

export function getSubscriptionState(subscription) {
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

export function subscriptionTitle(subscription) {
  const planName = subscription?.plan_name || 'Без тарифа'
  return subscription?.is_trial ? `${planName} (тест)` : planName
}

export function detectPlanType(plan) {
  const byFormat = String(plan?.plan_format || '').trim().toLowerCase()
  if (byFormat.startsWith('speed') || byFormat.startsWith('ускор') || byFormat.startsWith('скорост')) return 'speed'
  if (byFormat.startsWith('standard') || byFormat.startsWith('обыч') || byFormat.startsWith('стандарт')) return 'standard'
  const normalized = String(plan?.name || '').trim().toLowerCase()
  if (normalized.startsWith('скорост') || normalized.startsWith('ускор')) return 'speed'
  return 'standard'
}

export function getPlanDurationLabel(plan) {
  const label = String(plan?.duration_label || '').trim()
  if (label) return label
  return `${Number(plan?.duration_days || 0)} дней`
}

export function normalizeParamFlags(monitoring) {
  return {
    photo: monitoring?.include_photo ?? true,
    description: monitoring?.include_description ?? true,
    seller: monitoring?.include_seller_info ?? true,
    price_drop: monitoring?.notify_price_drop ?? true,
  }
}

export function normalizePromoCode(value) {
  return String(value || '').trim().toUpperCase().replace(/\s+/g, '')
}

function normalizeDraftTitle(value) {
  return String(value || '').trim()
}

function normalizeDraftUrl(value) {
  return String(value || '').trim()
}

export function hasMonitoringSettingsChanges(monitoring, draft, flags) {
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
