import { lazy } from 'react'
import { LoadingBlock, SUBSCRIPTION_VIEW, TABS } from './appShared.jsx'

const InfoScreen = lazy(() => import('./screens/InfoScreen.jsx'))
const SubscriptionsHomeScreen = lazy(() => import('./screens/SubscriptionsHomeScreen.jsx'))
const SubscriptionDetailScreen = lazy(() => import('./screens/SubscriptionDetailScreen.jsx'))
const SubscriptionBuyScreen = lazy(() => import('./screens/SubscriptionBuyScreen.jsx'))
const ProfileScreen = lazy(() => import('./screens/ProfileScreen.jsx'))

export default function ScreenRouter(props) {
  if (props.loading) return <LoadingBlock />

  if (props.tab === TABS.info) {
    return <InfoScreen miniappContent={props.miniappContent} />
  }

  if (props.tab === TABS.subscriptions && props.subscriptionView === SUBSCRIPTION_VIEW.home) {
    return (
      <SubscriptionsHomeScreen
        miniappContent={props.miniappContent}
        normalizedMonitorings={props.normalizedMonitorings}
        openSubscriptionDetails={props.openSubscriptionDetails}
        profile={props.profile}
        trialDays={props.trialDays}
        trialBusy={props.trialBusy}
        trialLabel={props.trialLabel}
        onActivateTrial={props.onActivateTrial}
        openBuyScreen={props.openBuyScreen}
      />
    )
  }

  if (props.tab === TABS.subscriptions && props.subscriptionView === SUBSCRIPTION_VIEW.detail) {
    return (
      <SubscriptionDetailScreen
        selectedMonitoring={props.selectedMonitoring}
        detailDraft={props.detailDraft}
        detailFlags={props.detailFlags}
        updateSelectedDraft={props.updateSelectedDraft}
        openBuyScreen={props.openBuyScreen}
        setParamFlags={props.setParamFlags}
        autoSaveStatus={props.autoSaveStatus}
        stopSelectedMonitoring={props.stopSelectedMonitoring}
        stopMonitoringBusy={props.stopMonitoringBusy}
        saveMonitoringBusy={props.saveMonitoringBusy}
        startSelectedMonitoringAndOpenBot={props.startSelectedMonitoringAndOpenBot}
        startMonitoringBusy={props.startMonitoringBusy}
        openBotWithAutoSave={props.openBotWithAutoSave}
      />
    )
  }

  if (props.tab === TABS.subscriptions && props.subscriptionView === SUBSCRIPTION_VIEW.buy) {
    return (
      <SubscriptionBuyScreen
        selectedType={props.selectedType}
        setSelectedType={props.setSelectedType}
        setSelectedPlanId={props.setSelectedPlanId}
        plansBySelectedType={props.plansBySelectedType}
        selectedPlan={props.selectedPlan}
        buyDraft={props.buyDraft}
        setBuyDraft={props.setBuyDraft}
        promoCode={props.promoCode}
        setPromoCode={props.setPromoCode}
        setPromoPreview={props.setPromoPreview}
        applyPromoCode={props.applyPromoCode}
        promoBusy={props.promoBusy}
        normalizedPromoCode={props.normalizedPromoCode}
        activePromoPreview={props.activePromoPreview}
        promoDiscount={props.promoDiscount}
        basePrice={props.basePrice}
        priceAfterPromo={props.priceAfterPromo}
        totalPrice={props.totalPrice}
        referralBalance={props.referralBalance}
        useReferralBalance={props.useReferralBalance}
        referralApplied={props.referralApplied}
        setUseReferralBalance={props.setUseReferralBalance}
        pendingPaymentId={props.pendingPaymentId}
        checkPurchaseStatus={props.checkPurchaseStatus}
        purchaseStatusBusy={props.purchaseStatusBusy}
        pendingPaymentUrl={props.pendingPaymentUrl}
        agreedToTerms={props.agreedToTerms}
        setAgreedToTerms={props.setAgreedToTerms}
        agreedToPrivacy={props.agreedToPrivacy}
        setAgreedToPrivacy={props.setAgreedToPrivacy}
        miniappContent={props.miniappContent}
        onPurchase={props.onPurchase}
        purchaseBusy={props.purchaseBusy}
      />
    )
  }

  if (props.tab === TABS.profile) {
    return (
      <ProfileScreen
        miniappContent={props.miniappContent}
        profile={props.profile}
        telegramId={props.telegramId}
        copyText={props.copyText}
        allSubscriptionsExpanded={props.allSubscriptionsExpanded}
        setAllSubscriptionsExpanded={props.setAllSubscriptionsExpanded}
        setStatusMessage={props.setStatusMessage}
      />
    )
  }

  return null
}
