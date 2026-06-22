const express = require('express');
const api = require('../services/backendApi');

const router = express.Router();
const ADMIN_BASE_PATH = process.env.ADMIN_BASE_PATH || "/admin";
const DEFAULT_MINIAPP_CONTENT = {
  support_title: 'Поддержка',
  support_url: 'https://t.me/your_support',
  news_title: 'Новостной канал',
  news_url: 'https://t.me/your_news',
  terms_title: 'Пользовательское соглашение',
  terms_url: 'https://t.me/your_terms',
  privacy_title: 'Политика конфиденциальности',
  privacy_url: 'https://t.me/your_privacy',
  subscriptions_title: 'Подписки',
  subscriptions_hint: 'Управление тарифом и переход к назначенным ботам.',
  profile_title: 'Профиль',
};
const PLAN_FORMAT_LABELS = {
  standard: 'Обычная',
  speed: 'Ускоренная',
};
const PROMO_DISCOUNT_LABELS = {
  percent: 'Процент',
  rub: 'Рубли',
};
const DEFAULT_PROXY_EXPIRES_DAYS = 30;

function toInt(value) {
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function normalizeDateInput(value) {
  const raw = String(value || '').trim();
  return raw || null;
}

function dateInputFromDays(value) {
  const raw = String(value || '').trim();
  if (!raw) return null;

  const days = toInt(raw);
  if (days === null || !Number.isInteger(days) || days <= 0) {
    throw new Error('Срок прокси должен быть целым числом больше 0 дней');
  }

  const date = new Date();
  date.setHours(12, 0, 0, 0);
  date.setDate(date.getDate() + days);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function normalizeProxyExpiresOn(body, defaultDays = null) {
  const expiresByDays = dateInputFromDays(body.expires_days || defaultDays);
  if (expiresByDays) return expiresByDays;
  return normalizeDateInput(body.expires_on);
}

function proxyUrlFromBody(body) {
  const alternativeProxyUrl = String(body.alternative_proxy_url || '').trim();
  const proxyUrl = String(body.proxy_url || '').trim();
  const selectedProxyUrl = alternativeProxyUrl || proxyUrl;

  if (!selectedProxyUrl) {
    throw new Error('Укажите прокси или альтернативную ссылку');
  }

  return selectedProxyUrl;
}

function emptyStats() {
  return {
    users_count: 0,
    active_monitorings: 0,
    active_subscriptions: 0,
    payments_total_rub: 0,
    payments_month_rub: 0,
    payments_month_label: '',
    active_bots: 0,
    active_proxies: 0,
    required_proxies: 0,
    proxy_capacity_monitorings: 0,
    missing_proxies: 0,
    proxy_capacity_ok: true,
  };
}

function normalizePercent(value) {
  const parsed = toInt(value);
  if (parsed === null) {
    throw new Error('Процент реферальной системы должен быть числом');
  }
  if (parsed < 0 || parsed > 100) {
    throw new Error('Процент реферальной системы должен быть в диапазоне 0-100');
  }
  return parsed;
}

function normalizePlanFormat(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'speed' || normalized === 'ускоренная' || normalized === 'скоростная') return 'speed';
  return 'standard';
}

function buildPlanName(planFormat, durationLabel, durationDays) {
  const formatLabel = planFormat === 'speed' ? PLAN_FORMAT_LABELS.speed : PLAN_FORMAT_LABELS.standard;
  const normalizedDuration = String(durationLabel || '').trim() || `${durationDays} дней`;
  return `${formatLabel} · ${normalizedDuration}`;
}

function parsePlanPayload(body) {
  const planFormat = normalizePlanFormat(body.plan_format);
  const durationDays = toInt(body.duration_days);
  const priceRub = toInt(body.price_rub);
  const linksLimit = toInt(body.links_limit) ?? 1;
  if (durationDays === null || durationDays <= 0) {
    throw new Error('Срок тарифа должен быть больше 0');
  }
  if (priceRub === null || priceRub < 0) {
    throw new Error('Стоимость тарифа должна быть 0 или больше');
  }
  if (linksLimit <= 0) {
    throw new Error('Лимит мониторингов должен быть больше 0');
  }
  const durationLabel = String(body.duration_label || '').trim() || `${durationDays} дней`;
  const fallbackDescription = `${PLAN_FORMAT_LABELS[planFormat]} тариф на ${durationLabel}`;
  const description = String(body.description || '').trim() || fallbackDescription;

  return {
    name: buildPlanName(planFormat, durationLabel, durationDays),
    plan_format: planFormat,
    duration_label: durationLabel,
    description,
    links_limit: linksLimit,
    duration_days: durationDays,
    price_rub: priceRub,
    is_active: body.is_active === 'on',
  };
}

function normalizePromoDiscountType(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'rub' || normalized === 'руб' || normalized === 'рубли') return 'rub';
  return 'percent';
}

function parsePromoPayload(body) {
  const discountType = normalizePromoDiscountType(body.discount_type);
  const discountValue = toInt(body.discount_value);
  if (!String(body.code || '').trim()) {
    throw new Error('Укажите промокод');
  }
  if (discountValue === null || discountValue <= 0) {
    throw new Error('Скидка должна быть больше 0');
  }
  if (discountType === 'percent' && discountValue > 100) {
    throw new Error('Процент скидки должен быть от 1 до 100');
  }

  return {
    code: String(body.code || '').trim(),
    local_name: String(body.local_name || '').trim() || null,
    discount_type: discountType,
    discount_value: discountValue,
    is_active: body.is_active === 'on',
  };
}

function sortPlans(plans) {
  const formatOrder = { standard: 0, speed: 1 };
  return [...plans].sort((a, b) => {
    const aFormat = normalizePlanFormat(a?.plan_format);
    const bFormat = normalizePlanFormat(b?.plan_format);
    const byFormat = (formatOrder[aFormat] ?? 9) - (formatOrder[bFormat] ?? 9);
    if (byFormat !== 0) return byFormat;
    const byDuration = (Number(a?.duration_days) || 0) - (Number(b?.duration_days) || 0);
    if (byDuration !== 0) return byDuration;
    const byPrice = (Number(a?.price_rub) || 0) - (Number(b?.price_rub) || 0);
    if (byPrice !== 0) return byPrice;
    return (Number(a?.id) || 0) - (Number(b?.id) || 0);
  });
}

function withAdminBase(path) {
  const cleanBase = ADMIN_BASE_PATH.endsWith("/") ? ADMIN_BASE_PATH.slice(0, -1) : ADMIN_BASE_PATH;
  return `${cleanBase}${path}`;
}

router.get('/', async (req, res) => {
  try {
    const stats = await api.getStats();
    const [plans, proxies, bots, trialSettings, referralSettings, miniappContent] = await Promise.all([
      api.getPlans(),
      api.getProxies(),
      api.getBots(),
      api.getTrialSettings(),
      api.getReferralSettings(),
      api.getMiniappContent(),
    ]);
    res.render('dashboard', {
      stats,
      plans,
      proxies,
      bots,
      trialSettings,
      referralSettings,
      miniappContent,
      error: null,
      success: req.query.success || null,
    });
  } catch (error) {
    res.render('dashboard', {
      stats: emptyStats(),
      plans: [],
      proxies: [],
      bots: [],
      trialSettings: { trial_days: 0 },
      referralSettings: { referral_reward_percent: 10 },
      miniappContent: DEFAULT_MINIAPP_CONTENT,
      error: error.message,
      success: null,
    });
  }
});

router.get('/plans', async (req, res) => {
  try {
    const plans = sortPlans(await api.getPlans());
    res.render('plans', {
      plans,
      planFormatLabels: PLAN_FORMAT_LABELS,
      error: req.query.error || null,
      success: req.query.success || null,
    });
  } catch (error) {
    res.render('plans', { plans: [], planFormatLabels: PLAN_FORMAT_LABELS, error: error.message, success: null });
  }
});

router.get('/plans/create', async (req, res) => {
  try {
    await api.createPlan(parsePlanPayload(req.body));
    res.redirect(withAdminBase('/plans?success=Тариф+добавлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/plans?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/plans/:id/update', async (req, res) => {
  try {
    await api.updatePlan(req.params.id, parsePlanPayload(req.body));
    res.redirect(withAdminBase('/plans?success=Тариф+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/plans?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/plans/:id/delete', async (req, res) => {
  try {
    await api.deletePlan(req.params.id);
    res.redirect(withAdminBase('/plans?success=Тариф+удален'));
  } catch (error) {
    res.redirect(withAdminBase(`/plans?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/promo-codes', async (req, res) => {
  try {
    const promoCodes = await api.getPromoCodes();
    res.render('promo-codes', {
      promoCodes,
      discountLabels: PROMO_DISCOUNT_LABELS,
      error: req.query.error || null,
      success: req.query.success || null,
    });
  } catch (error) {
    res.render('promo-codes', {
      promoCodes: [],
      discountLabels: PROMO_DISCOUNT_LABELS,
      error: error.message,
      success: null,
    });
  }
});

router.get('/promo-codes/:id/stats', async (req, res) => {
  const dateFrom = String(req.query.date_from || '').trim() || null;
  const dateTo = String(req.query.date_to || '').trim() || null;
  try {
    const [promoCodes, stats] = await Promise.all([
      api.getPromoCodes(),
      api.getPromoCodeStats(req.params.id, { dateFrom, dateTo }),
    ]);
    const promo = promoCodes.find((item) => String(item.id) === String(req.params.id)) || null;
    res.render('promo-code-stats', {
      promo,
      stats,
      dateFrom,
      dateTo,
      error: req.query.error || null,
    });
  } catch (error) {
    res.render('promo-code-stats', {
      promo: null,
      stats: null,
      dateFrom,
      dateTo,
      error: error.message,
    });
  }
});

router.get('/promo-codes/create', async (req, res) => {
  try {
    await api.createPromoCode(parsePromoPayload(req.body));
    res.redirect(withAdminBase('/promo-codes?success=Промокод+добавлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/promo-codes?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/promo-codes/:id/update', async (req, res) => {
  try {
    await api.updatePromoCode(req.params.id, parsePromoPayload(req.body));
    res.redirect(withAdminBase('/promo-codes?success=Промокод+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/promo-codes?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/promo-codes/:id/delete', async (req, res) => {
  try {
    await api.deletePromoCode(req.params.id);
    res.redirect(withAdminBase('/promo-codes?success=Промокод+удален'));
  } catch (error) {
    res.redirect(withAdminBase(`/promo-codes?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/proxies', async (req, res) => {
  try {
    const stats = await api.getStats();
    const proxies = await api.getProxies();
    res.render('proxies', { proxies, stats, error: null, success: req.query.success || null });
  } catch (error) {
    res.render('proxies', { proxies: [], stats: emptyStats(), error: error.message, success: null });
  }
});

router.get('/proxies/create', async (req, res) => {
  try {
    await api.createProxy({
      name: String(req.body.name || '').trim() || null,
      proxy_url: proxyUrlFromBody(req.body),
      change_ip_url: req.body.change_ip_url || null,
      is_active: req.body.is_active === 'on',
      expires_on: normalizeProxyExpiresOn(req.body, DEFAULT_PROXY_EXPIRES_DAYS),
    });
    res.redirect(withAdminBase('/proxies?success=Прокси+добавлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/proxies?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/proxies/:id/update', async (req, res) => {
  try {
    await api.updateProxy(req.params.id, {
      name: req.body.name,
      proxy_url: proxyUrlFromBody(req.body),
      change_ip_url: req.body.change_ip_url || null,
      is_active: req.body.is_active === 'on',
      expires_on: normalizeProxyExpiresOn(req.body),
    });
    res.redirect(withAdminBase('/proxies?success=Прокси+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/proxies?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/proxies/:id/active', async (req, res) => {
  try {
    await api.updateProxy(req.params.id, {
      is_active: Boolean(req.body.is_active),
    });
    res.json({ ok: true });
  } catch (error) {
    res.status(400).json({ ok: false, error: error.message });
  }
});

router.get('/proxies/:id/delete', async (req, res) => {
  try {
    await api.deleteProxy(req.params.id);
    res.redirect(withAdminBase('/proxies?success=Прокси+удален'));
  } catch (error) {
    res.redirect(withAdminBase(`/proxies?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/users', async (req, res) => {
  try {
    const users = await api.getUsers();
    res.render('users', { users, error: null, success: req.query.success || null });
  } catch (error) {
    res.render('users', { users: [], error: error.message, success: null });
  }
});

router.get('/users/admins', async (req, res) => {
  try {
    await api.addAdminUser({
      telegram_id: toInt(req.body.telegram_id),
      username: req.body.username || null,
      full_name: req.body.full_name || null,
    });
    res.redirect(withAdminBase('/users?success=Администратор+добавлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/users?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/users/:id/admin', async (req, res) => {
  try {
    await api.updateUserAdmin(req.params.id, {
      is_admin: Boolean(req.body.is_admin),
    });
    res.json({ ok: true });
  } catch (error) {
    res.status(400).json({ ok: false, error: error.message });
  }
});

router.get('/monitorings', async (req, res) => {
  try {
    const [monitorings, bots] = await Promise.all([api.getMonitorings(), api.getBots()]);
    res.render('monitorings', {
      monitorings,
      bots,
      error: req.query.error || null,
      success: req.query.success || null,
    });
  } catch (error) {
    res.render('monitorings', { monitorings: [], bots: [], error: error.message, success: null });
  }
});

router.get('/monitorings/:id/update', async (req, res) => {
  try {
    const payload = {
      title: req.body.title || null,
      url: req.body.url || '',
      is_active: req.body.is_active === 'on',
      include_photo: req.body.include_photo === 'on',
      include_description: req.body.include_description === 'on',
      include_seller_info: req.body.include_seller_info === 'on',
      notify_price_drop: req.body.notify_price_drop === 'on',
      detect_repost: req.body.detect_repost === 'on',
    };
    if (Object.prototype.hasOwnProperty.call(req.body, 'bot_id')) {
      payload.bot_id = toInt(req.body.bot_id) || 0;
    }
    await api.updateMonitoring(req.params.id, payload);
    res.redirect(withAdminBase('/monitorings?success=Мониторинг+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/monitorings?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/bots', async (req, res) => {
  try {
    const bots = await api.getBots();
    res.render('bots', { bots, error: null, success: req.query.success || null });
  } catch (error) {
    res.render('bots', { bots: [], error: error.message, success: null });
  }
});

router.get('/bots/create', async (req, res) => {
  try {
    await api.createBot({
      name: req.body.name,
      bot_token: req.body.bot_token,
      is_active: req.body.is_active === 'on',
      is_primary: req.body.is_primary === 'on',
    });
    res.redirect(withAdminBase('/bots?success=Бот+добавлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/bots?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/bots/:id/update', async (req, res) => {
  try {
    const payload = {
      name: req.body.name,
      is_active: req.body.is_active === 'on',
      bot_username: req.body.bot_username || null,
      is_primary: req.body.is_primary === 'on',
    };
    if (req.body.bot_token) {
      payload.bot_token = req.body.bot_token;
    }
    await api.updateBot(req.params.id, payload);
    res.redirect(withAdminBase('/bots?success=Бот+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/bots?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/bots/:id/delete', async (req, res) => {
  try {
    await api.deleteBot(req.params.id);
    res.redirect(withAdminBase('/bots?success=Бот+удален'));
  } catch (error) {
    res.redirect(withAdminBase(`/bots?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/payments', async (req, res) => {
  try {
    const [payments, plans, stats] = await Promise.all([api.getPayments(), api.getPlans(), api.getStats()]);
    res.render('payments', { payments, plans, stats, error: null, success: req.query.success || null });
  } catch (error) {
    res.render('payments', { payments: [], plans: [], stats: emptyStats(), error: error.message, success: null });
  }
});

router.get('/payments/create', async (req, res) => {
  try {
    await api.createPayment({
      telegram_id: toInt(req.body.telegram_id),
      plan_id: toInt(req.body.plan_id),
      amount_rub: toInt(req.body.amount_rub),
      provider: req.body.provider || 'manual',
    });
    res.redirect(withAdminBase('/payments?success=Платеж+создан'));
  } catch (error) {
    res.redirect(withAdminBase(`/payments?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/subscriptions/activate', async (req, res) => {
  try {
    await api.activateSubscription({
      telegram_id: toInt(req.body.telegram_id),
      plan_id: toInt(req.body.plan_id),
    });
    res.redirect(withAdminBase('/?success=Подписка+активирована'));
  } catch (error) {
    res.redirect(withAdminBase(`/?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/subscriptions/grant-days-all', async (req, res) => {
  try {
    const days = toInt(req.body.days);
    if (!days || days <= 0) throw new Error('Укажите количество дней больше 0');
    const result = await api.grantBonusDaysAll({ days });
    res.redirect(
      withAdminBase(
        `/?success=${encodeURIComponent(
          `Начислено ${result.days} дн. всем: пользователей ${result.affected_users}, подписок ${result.updated_subscriptions}`,
        )}`,
      ),
    );
  } catch (error) {
    res.redirect(withAdminBase(`/?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/broadcast', async (req, res) => {
  try {
    const text = String(req.body.text || '').trim();
    if (!text) throw new Error('Введите текст рассылки');
    const photoUrl = String(req.body.photo_url || '').trim() || null;
    const result = await api.broadcast({ text, photo_url: photoUrl });
    res.redirect(
      withAdminBase(
        `/?success=${encodeURIComponent(
          `Рассылка: всего ${result.total}, доставлено ${result.sent}, ошибок ${result.failed}`,
        )}`,
      ),
    );
  } catch (error) {
    res.redirect(withAdminBase(`/?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/subscriptions/grant-days-user', async (req, res) => {
  try {
    const days = toInt(req.body.days);
    const telegramId = toInt(req.body.telegram_id);
    if (!telegramId) throw new Error('Укажите Telegram ID');
    if (!days || days <= 0) throw new Error('Укажите количество дней больше 0');
    const result = await api.grantBonusDaysUser({ telegram_id: telegramId, days });
    res.redirect(
      withAdminBase(
        `/?success=${encodeURIComponent(
          `Начислено ${result.days} дн. пользователю ${telegramId}: подписок ${result.updated_subscriptions}`,
        )}`,
      ),
    );
  } catch (error) {
    res.redirect(withAdminBase(`/?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/trial-settings/update', async (req, res) => {
  try {
    await api.updateTrialSettings({
      trial_days: toInt(req.body.trial_days) || 0,
    });
    res.redirect(withAdminBase('/?success=Пробный+период+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/referral-settings/update', async (req, res) => {
  try {
    await api.updateReferralSettings({
      referral_reward_percent: normalizePercent(req.body.referral_reward_percent),
    });
    res.redirect(withAdminBase('/?success=Процент+реферальной+системы+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/miniapp-content/update', async (req, res) => {
  try {
    await api.updateMiniappContent({
      support_title: req.body.support_title,
      support_url: req.body.support_url,
      news_title: req.body.news_title,
      news_url: req.body.news_url,
      terms_title: req.body.terms_title,
      terms_url: req.body.terms_url,
      privacy_title: req.body.privacy_title,
      privacy_url: req.body.privacy_url,
      subscriptions_title: req.body.subscriptions_title,
      subscriptions_hint: req.body.subscriptions_hint,
      profile_title: req.body.profile_title,
    });
    res.redirect(withAdminBase('/?success=Контент+miniapp+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

module.exports = router;
