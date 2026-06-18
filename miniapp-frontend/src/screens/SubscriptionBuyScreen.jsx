import { getPlanDurationLabel, openExternal, TYPE_OPTIONS } from '../appShared.jsx'

export default function SubscriptionBuyScreen({
  selectedType,
  setSelectedType,
  setSelectedPlanId,
  plansBySelectedType,
  selectedPlan,
  buyDraft,
  setBuyDraft,
  promoCode,
  setPromoCode,
  setPromoPreview,
  applyPromoCode,
  promoBusy,
  normalizedPromoCode,
  activePromoPreview,
  promoDiscount,
  basePrice,
  priceAfterPromo,
  totalPrice,
  referralBalance,
  useReferralBalance,
  referralApplied,
  setUseReferralBalance,
  pendingPaymentId,
  checkPurchaseStatus,
  purchaseStatusBusy,
  pendingPaymentUrl,
  agreedToTerms,
  setAgreedToTerms,
  agreedToPrivacy,
  setAgreedToPrivacy,
  miniappContent,
  onPurchase,
  purchaseBusy,
}) {
  const selectedPlanDurationLabel = selectedPlan ? getPlanDurationLabel(selectedPlan) : '—'

  const openPaymentUrl = () => {
    if (window.Telegram?.WebApp?.openLink) {
      window.Telegram.WebApp.openLink(pendingPaymentUrl)
    } else {
      openExternal(pendingPaymentUrl)
    }
  }

  return (
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

      <h2 className="section-title">Промокод</h2>
      <input
        type="text"
        className="dark-input"
        placeholder="Введите промокод"
        value={promoCode}
        onChange={(event) => {
          setPromoCode(event.target.value)
          setPromoPreview(null)
        }}
      />
      <button
        type="button"
        className="secondary-btn"
        onClick={applyPromoCode}
        disabled={promoBusy || !normalizedPromoCode || !selectedPlan}
      >
        {promoBusy ? 'Проверяем...' : 'Применить промокод'}
      </button>
      {activePromoPreview && (
        <p className="hint-text hint-success">
          Промокод {activePromoPreview.code}: скидка {promoDiscount} ₽
        </p>
      )}

      <div className="buy-summary">
        <div className="summary-balance">Тариф: {selectedPlan?.name || '—'}</div>
        <div className="summary-balance">Срок: {selectedPlanDurationLabel} ({selectedPlan?.duration_days ?? 0} дней)</div>
        <div className="summary-balance">Цена тарифа: {basePrice}₽</div>
        {activePromoPreview && <div className="summary-balance">Скидка промокода: −{promoDiscount}₽</div>}
        {activePromoPreview && <div className="summary-balance">После промокода: {priceAfterPromo}₽</div>}
        <div className="summary-total">Итог: {totalPrice}₽</div>
        <div className="summary-balance">Реф. баланс: {referralBalance}₽</div>
        {useReferralBalance && <div className="summary-balance">Списать с реф. баланса: {referralApplied}₽</div>}
        <button
          type="button"
          className="check-row balance-row"
          onClick={() => setUseReferralBalance((prev) => !prev)}
        >
          <span className={`check-box ${useReferralBalance ? 'checked' : ''}`} />
          <span>Использовать реф. баланс для оплаты</span>
        </button>
      </div>

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
            <button type="button" className="secondary-btn" onClick={openPaymentUrl}>
              Открыть оплату снова
            </button>
          )}
        </div>
      )}

      <div className="buy-summary">
        <button
          type="button"
          className="check-row"
          onClick={() => setAgreedToTerms((prev) => !prev)}
        >
          <span className={`check-box ${agreedToTerms ? 'checked' : ''}`} />
          <span>
            Согласен с{' '}
            <a
              href={miniappContent?.terms_url || '#'}
              target="_blank"
              rel="noreferrer"
              onClick={(event) => {
                event.stopPropagation()
                if (miniappContent?.terms_url) {
                  event.preventDefault()
                  openExternal(miniappContent.terms_url)
                }
              }}
            >
              пользовательским соглашением
            </a>
          </span>
        </button>

        <button
          type="button"
          className="check-row"
          onClick={() => setAgreedToPrivacy((prev) => !prev)}
        >
          <span className={`check-box ${agreedToPrivacy ? 'checked' : ''}`} />
          <span>
            Согласен с{' '}
            <a
              href={miniappContent?.privacy_url || '#'}
              target="_blank"
              rel="noreferrer"
              onClick={(event) => {
                event.stopPropagation()
                if (miniappContent?.privacy_url) {
                  event.preventDefault()
                  openExternal(miniappContent.privacy_url)
                }
              }}
            >
              политикой конфиденциальности
            </a>
          </span>
        </button>
      </div>

      <button
        type="button"
        className="primary-btn"
        onClick={onPurchase}
        disabled={!selectedPlan || purchaseBusy || purchaseStatusBusy || !agreedToTerms || !agreedToPrivacy}
      >
        {purchaseBusy ? 'Создание платежа...' : totalPrice <= 0 ? 'Активировать подписку' : 'Оплатить через ЮKassa (СБП)'}
      </button>
    </section>
  )
}
