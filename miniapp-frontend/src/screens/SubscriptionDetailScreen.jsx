import { buildSubscriptionBotLink, formatDateTime, PARAM_OPTIONS } from '../appShared.jsx'

export default function SubscriptionDetailScreen({
  selectedMonitoring,
  detailDraft,
  detailFlags,
  updateSelectedDraft,
  openBuyScreen,
  setParamFlags,
  autoSaveStatus,
  stopSelectedMonitoring,
  stopMonitoringBusy,
  saveMonitoringBusy,
  startSelectedMonitoringAndOpenBot,
  startMonitoringBusy,
  openBotWithAutoSave,
}) {
  const detailBotLink = selectedMonitoring ? buildSubscriptionBotLink(selectedMonitoring.bot) : null

  return (
    <section className="screen-block">
      {!selectedMonitoring && (
        <div className="empty-card">Подписка не выбрана. Перейдите в список подписок.</div>
      )}

      {selectedMonitoring && (
        <>
          <h1 className="screen-title">{detailDraft.title || selectedMonitoring.title || 'Подписка'}</h1>

          <p className="hint-text">
            {selectedMonitoring.subscription_ends_at
              ? selectedMonitoring.subscription_is_trial
                ? `Пробный период до: ${formatDateTime(selectedMonitoring.subscription_ends_at)}`
                : `Подписка действует до: ${formatDateTime(selectedMonitoring.subscription_ends_at)}${
                    selectedMonitoring.subscription_plan_name ? ` · ${selectedMonitoring.subscription_plan_name}` : ''
                  }`
              : 'Подписка не активна'}
          </p>

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
  )
}
