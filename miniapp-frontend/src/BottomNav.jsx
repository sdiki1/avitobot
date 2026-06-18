import { IconHome, IconProfile, IconTicket, SUBSCRIPTION_VIEW, TABS } from './appShared.jsx'

export default function BottomNav({ tab, setTab, subscriptionView, setSubscriptionView }) {
  return (
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
  )
}
