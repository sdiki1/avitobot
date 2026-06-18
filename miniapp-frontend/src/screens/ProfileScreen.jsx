import {
  botShortName,
  buildSubscriptionBotLink,
  CopyIcon,
  formatDateTime,
  getSubscriptionState,
  IconChevron,
  isCurrentSubscription,
  openExternal,
  subscriptionTitle,
} from '../appShared.jsx'

export default function ProfileScreen({
  miniappContent,
  profile,
  telegramId,
  copyText,
  allSubscriptionsExpanded,
  setAllSubscriptionsExpanded,
  setStatusMessage,
}) {
  const profileSubscriptions = Array.isArray(profile?.subscriptions) ? profile.subscriptions : []
  const profileCurrentSubscriptions = profileSubscriptions.filter((item) => isCurrentSubscription(item))
  const fallbackCurrentSubscriptions =
    profileCurrentSubscriptions.length > 0
      ? profileCurrentSubscriptions
      : profile?.subscription
        ? [profile.subscription]
        : []
  const assignedBots = Array.isArray(profile?.assigned_bots) ? profile.assigned_bots : []

  return (
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
                      <span>
                        {bot?.subscription_ends_at
                          ? bot.subscription_is_trial
                            ? `Пробный период до: ${formatDateTime(bot.subscription_ends_at)}`
                            : `Подписка до: ${formatDateTime(bot.subscription_ends_at)}`
                          : 'Подписка не активна'}
                      </span>
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
  )
}
