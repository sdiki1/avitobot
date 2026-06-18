import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import BottomNav from './BottomNav.jsx'
import {
  DEFAULT_PARAM_FLAGS,
  detectPlanType,
  hasMonitoringSettingsChanges,
  normalizeParamFlags,
  normalizePromoCode,
  SUBSCRIPTION_VIEW,
  TABS,
} from './appShared.jsx'

const ScreenRouter = lazy(() => import('./ScreenRouter.jsx'))

function getTelegramInitData() {
  const webapp = window.Telegram?.WebApp
  if (!webapp) return null
  webapp.ready()
  if (!webapp.initData || typeof webapp.initData !== 'string') return null
  return webapp.initData
}

function waitForTelegramWebApp(timeoutMs = 1500) {
  if (window.Telegram?.WebApp) return Promise.resolve()

  return new Promise((resolve) => {
    const startedAt = Date.now()
    const timerId = window.setInterval(() => {
      if (window.Telegram?.WebApp || Date.now() - startedAt >= timeoutMs) {
        window.clearInterval(timerId)
        resolve()
      }
    }, 50)
  })
}

function getAuthTokenFromQuery() {
  return new URLSearchParams(window.location.search).get('auth')
}

function getPaymentIdFromQuery() {
  const raw = new URLSearchParams(window.location.search).get('payment_id')
  const parsed = Number(raw)
  if (!Number.isFinite(parsed) || parsed <= 0) return null
  return Math.trunc(parsed)
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
  const [miniappContent, setMiniappContent] = useState(null)

  const [selectedMonitoringId, setSelectedMonitoringId] = useState(null)
  const [drafts, setDrafts] = useState({})
  const [paramFlags, setParamFlags] = useState({})

  const [purchaseBusy, setPurchaseBusy] = useState(false)
  const [purchaseStatusBusy, setPurchaseStatusBusy] = useState(false)
  const [trialBusy, setTrialBusy] = useState(false)
  const [saveMonitoringBusy, setSaveMonitoringBusy] = useState(false)
  const [startMonitoringBusy, setStartMonitoringBusy] = useState(false)
  const [stopMonitoringBusy, setStopMonitoringBusy] = useState(false)
  const [autoSaveStatus, setAutoSaveStatus] = useState('idle')
  const [pendingPaymentId, setPendingPaymentId] = useState(null)
  const [pendingPaymentUrl, setPendingPaymentUrl] = useState('')
  const [selectedType, setSelectedType] = useState('standard')
  const [selectedPlanId, setSelectedPlanId] = useState(null)
  const [useReferralBalance, setUseReferralBalance] = useState(false)
  const [promoCode, setPromoCode] = useState('')
  const [promoPreview, setPromoPreview] = useState(null)
  const [promoBusy, setPromoBusy] = useState(false)
  const [agreedToTerms, setAgreedToTerms] = useState(false)
  const [agreedToPrivacy, setAgreedToPrivacy] = useState(false)
  const [buyDraft, setBuyDraft] = useState({ title: '', url: '' })
  const [buyTargetMonitoringId, setBuyTargetMonitoringId] = useState(null)
  const [allSubscriptionsExpanded, setAllSubscriptionsExpanded] = useState(true)

  useEffect(() => {
    if (window.Telegram && window.Telegram.WebApp) {
      window.Telegram.WebApp.ready?.()
      window.Telegram.WebApp.expand()
    }
  }, [])

  const normalizedMonitorings = useMemo(() => {
    if (monitorings.length > 0) {
      return monitorings.map((item) => ({ ...item, uid: String(item.id) }))
    }

    return []
  }, [monitorings])

  const selectedMonitoring = useMemo(
    () => normalizedMonitorings.find((item) => item.uid === selectedMonitoringId) || null,
    [normalizedMonitorings, selectedMonitoringId],
  )

  const plansBySelectedType = useMemo(() => {
    return plans
      .filter((plan) => detectPlanType(plan) === selectedType)
      .sort((a, b) => {
        const byDuration = Number(a.duration_days || 0) - Number(b.duration_days || 0)
        if (byDuration !== 0) return byDuration
        const byPrice = Number(a.price_rub || 0) - Number(b.price_rub || 0)
        if (byPrice !== 0) return byPrice
        return Number(a.id || 0) - Number(b.id || 0)
      })
  }, [plans, selectedType])

  useEffect(() => {
    if (!plans.length) return
    const hasCurrentType = plans.some((plan) => detectPlanType(plan) === selectedType)
    if (!hasCurrentType) {
      setSelectedType(detectPlanType(plans[0]))
    }
  }, [plans, selectedType])

  useEffect(() => {
    if (plansBySelectedType.length === 0) {
      setSelectedPlanId(null)
      return
    }
    const hasSelected = plansBySelectedType.some((plan) => Number(plan.id) === Number(selectedPlanId))
    if (!hasSelected) {
      setSelectedPlanId(Number(plansBySelectedType[0].id))
    }
  }, [plansBySelectedType, selectedPlanId])

  const selectedPlan = useMemo(() => {
    if (plansBySelectedType.length === 0) return plans[0] || null
    const byId = plansBySelectedType.find((plan) => Number(plan.id) === Number(selectedPlanId))
    return byId || plansBySelectedType[0]
  }, [plans, plansBySelectedType, selectedPlanId])

  const normalizedPromoCode = normalizePromoCode(promoCode)
  const activePromoPreview = useMemo(() => {
    if (!promoPreview || !selectedPlan) return null
    if (normalizePromoCode(promoPreview.code) !== normalizedPromoCode) return null
    if (Number(promoPreview.plan_id || 0) !== Number(selectedPlan.id || 0)) return null
    return promoPreview
  }, [normalizedPromoCode, promoPreview, selectedPlan])

  const referralBalance = profile?.user?.referral_balance_rub ?? 0
  const basePrice = Number(selectedPlan?.price_rub || 0)
  const promoDiscount = Math.min(basePrice, Number(activePromoPreview?.discount_rub || 0))
  const priceAfterPromo = Math.max(0, basePrice - promoDiscount)
  const referralApplied = useReferralBalance ? Math.min(referralBalance, priceAfterPromo) : 0
  const totalPrice = Math.max(0, priceAfterPromo - referralApplied)

  const loadData = async (tgId) => {
    const { loadDataAction } = await import('./appActions.js')
    return loadDataAction({
      tgId,
      setProfile,
      setPlans,
      setMonitorings,
      setMiniappContent,
      setDrafts,
      setParamFlags,
      setSelectedMonitoringId,
    })
  }

  useEffect(() => {
    const init = async () => {
      try {
        const { getAuthSession, resolveAuthToken, signInMiniApp } = await import('./api')
        let resolvedTelegramId = null
        let authError = false

        await waitForTelegramWebApp()
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

        const returnedPaymentId = getPaymentIdFromQuery()
        if (returnedPaymentId) {
          setPendingPaymentId(returnedPaymentId)
          await checkPurchaseStatus(returnedPaymentId, resolvedTelegramId)
        }
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
        [uid]: normalizeParamFlags(monitoring),
      }
    })
  }

  const openSubscriptionDetails = (monitoring) => {
    ensureDraft(monitoring)
    setSelectedMonitoringId(String(monitoring.uid))
    setSubscriptionView(SUBSCRIPTION_VIEW.detail)
  }

  const openBuyScreen = ({ renew = false } = {}) => {
    if (renew && selectedMonitoring) {
      ensureDraft(selectedMonitoring)
      const draft = drafts[selectedMonitoring.uid] || {
        title: selectedMonitoring.title || '',
        url: selectedMonitoring.url || '',
      }
      setBuyDraft({ title: draft.title || '', url: draft.url || '' })
      setBuyTargetMonitoringId(Number(selectedMonitoring.id))
    } else {
      setBuyDraft({ title: '', url: '' })
      setBuyTargetMonitoringId(null)
    }
    setPromoCode('')
    setPromoPreview(null)
    setAgreedToTerms(false)
    setAgreedToPrivacy(false)
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
      setSubscriptionView(buyTargetMonitoringId ? SUBSCRIPTION_VIEW.detail : SUBSCRIPTION_VIEW.home)
      return
    }

    window.Telegram?.WebApp?.close?.()
  }, [buyTargetMonitoringId, subscriptionView, tab])

  const applyPromoCode = async () => {
    const { applyPromoCodeAction } = await import('./appActions.js')
    return applyPromoCodeAction({
      telegramId,
      selectedPlan,
      promoBusy,
      normalizedPromoCode,
      setPromoBusy,
      setPromoCode,
      setPromoPreview,
      setStatusMessage,
    })
  }

  const onPurchase = async () => {
    const { purchaseSubscriptionAction } = await import('./appActions.js')
    return purchaseSubscriptionAction({
      telegramId,
      selectedPlan,
      purchaseBusy,
      normalizedPromoCode,
      activePromoPreview,
      selectedType,
      useReferralBalance,
      buyTargetMonitoringId,
      buyDraft,
      setPurchaseBusy,
      setPendingPaymentId,
      setPendingPaymentUrl,
      setStatusMessage,
      setSubscriptionView,
      loadData,
      totalPrice,
    })
  }

  const checkPurchaseStatus = async (explicitPaymentId = null, explicitTelegramId = null) => {
    const { checkPurchaseStatusAction } = await import('./appActions.js')
    return checkPurchaseStatusAction({
      explicitPaymentId,
      explicitTelegramId,
      pendingPaymentId,
      telegramId,
      purchaseStatusBusy,
      buyTargetMonitoringId,
      setPurchaseStatusBusy,
      setPendingPaymentId,
      setPendingPaymentUrl,
      setStatusMessage,
      setSubscriptionView,
      loadData,
    })
  }

  const trialDays = profile?.trial_days ?? 0
  const trialLabel = trialDays > 0 ? `${trialDays} ${trialDays === 1 ? 'день' : trialDays < 5 ? 'дня' : 'дней'}` : ''

  const onActivateTrial = async () => {
    const { activateTrialAction } = await import('./appActions.js')
    return activateTrialAction({
      telegramId,
      trialBusy,
      trialLabel,
      setTrialBusy,
      setStatusMessage,
      loadData,
    })
  }

  const applyMonitoringUpdateToState = useCallback((updatedMonitoring) => {
    if (!updatedMonitoring?.id) return
    const uid = String(updatedMonitoring.id)

    setMonitorings((prev) =>
      prev.map((item) => (Number(item.id) === Number(updatedMonitoring.id) ? updatedMonitoring : item)),
    )
    setDrafts((prev) => ({
      ...prev,
      [uid]: {
        title: updatedMonitoring.title || '',
        url: updatedMonitoring.url || '',
      },
    }))
    setParamFlags((prev) => ({
      ...prev,
      [uid]: normalizeParamFlags(updatedMonitoring),
    }))
  }, [])

  const persistMonitoringSettings = useCallback(
    async ({ monitoring, draft, flags, extraPatch = {}, force = false }) => {
      const { persistMonitoringSettingsAction } = await import('./appActions.js')
      return persistMonitoringSettingsAction({
        telegramId,
        monitoring,
        draft,
        flags,
        extraPatch,
        force,
        applyMonitoringUpdateToState,
      })
    },
    [applyMonitoringUpdateToState, telegramId],
  )

  const stopSelectedMonitoring = async () => {
    const { stopSelectedMonitoringAction } = await import('./appActions.js')
    return stopSelectedMonitoringAction({
      telegramId,
      selectedMonitoring,
      stopMonitoringBusy,
      drafts,
      paramFlags,
      setStopMonitoringBusy,
      setStatusMessage,
      persistMonitoringSettings,
    })
  }

  const startSelectedMonitoringAndOpenBot = async () => {
    const { startSelectedMonitoringAndOpenBotAction } = await import('./appActions.js')
    return startSelectedMonitoringAndOpenBotAction({
      telegramId,
      selectedMonitoring,
      startMonitoringBusy,
      stopMonitoringBusy,
      saveMonitoringBusy,
      drafts,
      paramFlags,
      setStartMonitoringBusy,
      setStatusMessage,
      persistMonitoringSettings,
    })
  }

  const openBotWithAutoSave = async () => {
    const { openBotWithAutoSaveAction } = await import('./appActions.js')
    return openBotWithAutoSaveAction({
      telegramId,
      selectedMonitoring,
      startMonitoringBusy,
      stopMonitoringBusy,
      saveMonitoringBusy,
      drafts,
      paramFlags,
      setStartMonitoringBusy,
      setStatusMessage,
      persistMonitoringSettings,
    })
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

  const detailDraft = selectedMonitoring
    ? drafts[selectedMonitoring.uid] || {
        title: selectedMonitoring.title || '',
        url: selectedMonitoring.url || '',
      }
    : { title: '', url: '' }

  const detailFlags = selectedMonitoring
    ? paramFlags[selectedMonitoring.uid] || normalizeParamFlags(selectedMonitoring)
    : DEFAULT_PARAM_FLAGS

  useEffect(() => {
    if (!telegramId || !selectedMonitoring || selectedMonitoring.virtual) {
      setAutoSaveStatus('idle')
      return
    }
    if (startMonitoringBusy || stopMonitoringBusy) {
      return
    }

    const draft = drafts[selectedMonitoring.uid] || { title: selectedMonitoring.title || '', url: selectedMonitoring.url || '' }
    const flags = paramFlags[selectedMonitoring.uid] || normalizeParamFlags(selectedMonitoring)
    if (!hasMonitoringSettingsChanges(selectedMonitoring, draft, flags)) {
      setAutoSaveStatus('idle')
      return
    }

    const timerId = setTimeout(async () => {
      if (saveMonitoringBusy || startMonitoringBusy || stopMonitoringBusy) return
      try {
        setSaveMonitoringBusy(true)
        setAutoSaveStatus('saving')
        await persistMonitoringSettings({
          monitoring: selectedMonitoring,
          draft,
          flags,
        })
        setAutoSaveStatus('saved')
      } catch (error) {
        const detail = error?.response?.data?.detail || error?.message || 'Ошибка автосохранения'
        setAutoSaveStatus('error')
        setStatusMessage(`Ошибка: ${detail}`)
      } finally {
        setSaveMonitoringBusy(false)
      }
    }, 700)

    return () => clearTimeout(timerId)
  }, [
    drafts,
    paramFlags,
    persistMonitoringSettings,
    saveMonitoringBusy,
    selectedMonitoring,
    startMonitoringBusy,
    stopMonitoringBusy,
    telegramId,
  ])


  return (
    <div className="app-root">
      <div className="mobile-shell">
        <main className="main-content">
          {statusMessage && <div className="status-banner">{statusMessage}</div>}
          <Suspense fallback={null}>
            <ScreenRouter
              loading={loading}
              tab={tab}
              subscriptionView={subscriptionView}
              miniappContent={miniappContent}
              normalizedMonitorings={normalizedMonitorings}
              openSubscriptionDetails={openSubscriptionDetails}
              profile={profile}
              trialDays={trialDays}
              trialBusy={trialBusy}
              trialLabel={trialLabel}
              onActivateTrial={onActivateTrial}
              openBuyScreen={openBuyScreen}
              selectedMonitoring={selectedMonitoring}
              detailDraft={detailDraft}
              detailFlags={detailFlags}
              updateSelectedDraft={updateSelectedDraft}
              setParamFlags={setParamFlags}
              autoSaveStatus={autoSaveStatus}
              stopSelectedMonitoring={stopSelectedMonitoring}
              stopMonitoringBusy={stopMonitoringBusy}
              saveMonitoringBusy={saveMonitoringBusy}
              startSelectedMonitoringAndOpenBot={startSelectedMonitoringAndOpenBot}
              startMonitoringBusy={startMonitoringBusy}
              openBotWithAutoSave={openBotWithAutoSave}
              selectedType={selectedType}
              setSelectedType={setSelectedType}
              setSelectedPlanId={setSelectedPlanId}
              plansBySelectedType={plansBySelectedType}
              selectedPlan={selectedPlan}
              buyDraft={buyDraft}
              setBuyDraft={setBuyDraft}
              promoCode={promoCode}
              setPromoCode={setPromoCode}
              setPromoPreview={setPromoPreview}
              applyPromoCode={applyPromoCode}
              promoBusy={promoBusy}
              normalizedPromoCode={normalizedPromoCode}
              activePromoPreview={activePromoPreview}
              promoDiscount={promoDiscount}
              basePrice={basePrice}
              priceAfterPromo={priceAfterPromo}
              totalPrice={totalPrice}
              referralBalance={referralBalance}
              useReferralBalance={useReferralBalance}
              referralApplied={referralApplied}
              setUseReferralBalance={setUseReferralBalance}
              pendingPaymentId={pendingPaymentId}
              checkPurchaseStatus={checkPurchaseStatus}
              purchaseStatusBusy={purchaseStatusBusy}
              pendingPaymentUrl={pendingPaymentUrl}
              agreedToTerms={agreedToTerms}
              setAgreedToTerms={setAgreedToTerms}
              agreedToPrivacy={agreedToPrivacy}
              setAgreedToPrivacy={setAgreedToPrivacy}
              onPurchase={onPurchase}
              purchaseBusy={purchaseBusy}
              telegramId={telegramId}
              copyText={copyText}
              allSubscriptionsExpanded={allSubscriptionsExpanded}
              setAllSubscriptionsExpanded={setAllSubscriptionsExpanded}
              setStatusMessage={setStatusMessage}
            />
          </Suspense>
        </main>

        <BottomNav
          tab={tab}
          setTab={setTab}
          subscriptionView={subscriptionView}
          setSubscriptionView={setSubscriptionView}
        />
      </div>
    </div>
  )
}
