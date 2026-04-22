const express = require('express');
const api = require('../services/backendApi');

const router = express.Router();
const ADMIN_BASE_PATH = process.env.ADMIN_BASE_PATH || "/admin";
const DEFAULT_MINIAPP_CONTENT = {
  support_title: 'Поддержка',
  support_url: 'https://t.me/your_support',
  faq_title: 'Частые вопросы',
  faq_url: 'https://t.me/your_faq',
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

function toInt(value) {
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function normalizeDateInput(value) {
  const raw = String(value || '').trim();
  return raw || null;
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
    const [stats, plans, proxies, bots, trialSettings, miniappContent] = await Promise.all([
      api.getStats(),
      api.getPlans(),
      api.getProxies(),
      api.getBots(),
      api.getTrialSettings(),
      api.getMiniappContent(),
    ]);
    res.render('dashboard', {
      stats,
      plans,
      proxies,
      bots,
      trialSettings,
      miniappContent,
      error: null,
      success: req.query.success || null,
    });
  } catch (error) {
    res.render('dashboard', {
      stats: { users_count: 0, active_monitorings: 0, active_subscriptions: 0, payments_total_rub: 0, active_bots: 0 },
      plans: [],
      proxies: [],
      bots: [],
      trialSettings: { trial_days: 0 },
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

router.post('/plans', async (req, res) => {
  try {
    await api.createPlan(parsePlanPayload(req.body));
    res.redirect(withAdminBase('/plans?success=Тариф+добавлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/plans?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.post('/plans/:id/update', async (req, res) => {
  try {
    await api.updatePlan(req.params.id, parsePlanPayload(req.body));
    res.redirect(withAdminBase('/plans?success=Тариф+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/plans?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.post('/plans/:id/delete', async (req, res) => {
  try {
    await api.deletePlan(req.params.id);
    res.redirect(withAdminBase('/plans?success=Тариф+удален'));
  } catch (error) {
    res.redirect(withAdminBase(`/plans?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/proxies', async (req, res) => {
  try {
    const proxies = await api.getProxies();
    res.render('proxies', { proxies, error: null, success: req.query.success || null });
  } catch (error) {
    res.render('proxies', { proxies: [], error: error.message, success: null });
  }
});

router.post('/proxies', async (req, res) => {
  try {
    await api.createProxy({
      name: req.body.name,
      proxy_url: req.body.proxy_url,
      change_ip_url: req.body.change_ip_url || null,
      is_active: req.body.is_active === 'on',
      expires_on: normalizeDateInput(req.body.expires_on),
    });
    res.redirect(withAdminBase('/proxies?success=Прокси+добавлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/proxies?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.post('/proxies/:id/update', async (req, res) => {
  try {
    await api.updateProxy(req.params.id, {
      name: req.body.name,
      proxy_url: req.body.proxy_url,
      change_ip_url: req.body.change_ip_url || null,
      is_active: req.body.is_active === 'on',
      expires_on: normalizeDateInput(req.body.expires_on),
    });
    res.redirect(withAdminBase('/proxies?success=Прокси+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/proxies?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.post('/proxies/:id/active', async (req, res) => {
  try {
    await api.updateProxy(req.params.id, {
      is_active: Boolean(req.body.is_active),
    });
    res.json({ ok: true });
  } catch (error) {
    res.status(400).json({ ok: false, error: error.message });
  }
});

router.post('/proxies/:id/delete', async (req, res) => {
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

router.post('/users/admins', async (req, res) => {
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

router.post('/users/:id/admin', async (req, res) => {
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
    const monitorings = await api.getMonitorings();
    res.render('monitorings', { monitorings, error: req.query.error || null, success: req.query.success || null });
  } catch (error) {
    res.render('monitorings', { monitorings: [], error: error.message, success: null });
  }
});

router.post('/monitorings/:id/update', async (req, res) => {
  try {
    await api.updateMonitoring(req.params.id, {
      title: req.body.title || null,
      url: req.body.url || '',
      is_active: req.body.is_active === 'on',
      include_photo: req.body.include_photo === 'on',
      include_description: req.body.include_description === 'on',
      include_seller_info: req.body.include_seller_info === 'on',
      notify_price_drop: req.body.notify_price_drop === 'on',
    });
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

router.post('/bots', async (req, res) => {
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

router.post('/bots/:id/update', async (req, res) => {
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

router.post('/bots/:id/delete', async (req, res) => {
  try {
    await api.deleteBot(req.params.id);
    res.redirect(withAdminBase('/bots?success=Бот+удален'));
  } catch (error) {
    res.redirect(withAdminBase(`/bots?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/payments', async (req, res) => {
  try {
    const [payments, plans] = await Promise.all([api.getPayments(), api.getPlans()]);
    res.render('payments', { payments, plans, error: null, success: req.query.success || null });
  } catch (error) {
    res.render('payments', { payments: [], plans: [], error: error.message, success: null });
  }
});

router.post('/payments', async (req, res) => {
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

router.post('/subscriptions/activate', async (req, res) => {
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

router.post('/trial-settings/update', async (req, res) => {
  try {
    await api.updateTrialSettings({
      trial_days: toInt(req.body.trial_days) || 0,
    });
    res.redirect(withAdminBase('/?success=Пробный+период+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.post('/miniapp-content/update', async (req, res) => {
  try {
    await api.updateMiniappContent({
      support_title: req.body.support_title,
      support_url: req.body.support_url,
      faq_title: req.body.faq_title,
      faq_url: req.body.faq_url,
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
