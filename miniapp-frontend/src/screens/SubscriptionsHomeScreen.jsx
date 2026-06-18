import { botShortName, formatDateTime, IconChevron } from '../appShared.jsx'

export default function SubscriptionsHomeScreen({
  miniappContent,
  normalizedMonitorings,
  openSubscriptionDetails,
  profile,
  trialDays,
  trialBusy,
  trialLabel,
  onActivateTrial,
  openBuyScreen,
}) {
  return (
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
              <span>
                {monitoring.subscription_ends_at
                  ? monitoring.subscription_is_trial
                    ? `Пробный период до: ${formatDateTime(monitoring.subscription_ends_at)}`
                    : `Подписка до: ${formatDateTime(monitoring.subscription_ends_at)}`
                  : 'Подписка не активна'}
              </span>
            </span>

            <span className="subscription-chevron">
              <IconChevron />
            </span>
          </button>
        ))}
      </div>

      {profile?.can_activate_trial && trialDays > 0 && (
        <button type="button" className="secondary-btn" onClick={onActivateTrial} disabled={trialBusy}>
          {trialBusy ? 'Активация...' : `Начать пробный период (${trialLabel})`}
        </button>
      )}

      <button
        type="button"
        className="primary-btn purchase-bottom-btn"
        onClick={() => openBuyScreen({ renew: false })}
      >
        Купить подписку
      </button>
    </section>
  )
}
