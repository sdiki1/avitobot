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
const MINIAPP_PLAN_DEFINITIONS = [
  {
    key: 'standard',
    name: 'Стандартная',
    defaults: {
      description: 'Стандартная подписка',
      links_limit: 1,
      duration_days: 30,
      price_rub: 500,
      is_active: true,
    },
  },
  {
    key: 'speed',
    name: 'Скоростная',
    defaults: {
      description: 'Скоростная подписка',
      links_limit: 1,
      duration_days: 30,
      price_rub: 900,
      is_active: true,
    },
  },
];

function toInt(value) {
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function normalizePlanName(value) {
  return String(value || '').trim().toLowerCase();
}

function composeMiniappPlans(plans) {
  const allPlans = Array.isArray(plans) ? plans : [];
  return MINIAPP_PLAN_DEFINITIONS.map((preset) => {
    const existing = allPlans.find((plan) => normalizePlanName(plan?.name) === normalizePlanName(preset.name));
    return {
      key: preset.key,
      id: existing?.id || null,
      name: preset.name,
      description: existing?.description ?? preset.defaults.description,
      links_limit: existing?.links_limit ?? preset.defaults.links_limit,
      duration_days: existing?.duration_days ?? preset.defaults.duration_days,
      price_rub: existing?.price_rub ?? preset.defaults.price_rub,
      is_active: existing?.is_active ?? preset.defaults.is_active,
    };
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
    const allPlans = await api.getPlans();
    const miniappPlans = composeMiniappPlans(allPlans);
    const visibleIds = new Set(miniappPlans.map((plan) => Number(plan.id)).filter(Boolean));
    const hiddenPlansCount = allPlans.filter((plan) => !visibleIds.has(Number(plan.id))).length;
    res.render('plans', {
      plans: miniappPlans,
      hiddenPlansCount,
      error: req.query.error || null,
      success: req.query.success || null,
    });
  } catch (error) {
    res.render('plans', { plans: composeMiniappPlans([]), hiddenPlansCount: 0, error: error.message, success: null });
  }
});

router.post('/plans', async (req, res) => {
  res.redirect(withAdminBase('/plans?error=Создание+произвольных+тарифов+отключено'));
});

router.post('/plans/:id/update', async (req, res) => {
  res.redirect(withAdminBase('/plans?error=Редактирование+доступно+только+для+тарифов+miniapp'));
});

router.post('/plans/miniapp/:key/save', async (req, res) => {
  try {
    const preset = MINIAPP_PLAN_DEFINITIONS.find((item) => item.key === req.params.key);
    if (!preset) {
      throw new Error('Неизвестный тип тарифа');
    }

    const payload = {
      name: preset.name,
      description: req.body.description || preset.defaults.description,
      links_limit: toInt(req.body.links_limit) ?? preset.defaults.links_limit,
      duration_days: toInt(req.body.duration_days) ?? preset.defaults.duration_days,
      price_rub: toInt(req.body.price_rub) ?? preset.defaults.price_rub,
      is_active: req.body.is_active === 'on',
    };

    const allPlans = await api.getPlans();
    const requestedId = toInt(req.body.plan_id);
    let existingPlan = null;
    if (requestedId !== null) {
      existingPlan = allPlans.find((plan) => Number(plan.id) === requestedId) || null;
    }
    if (!existingPlan) {
      existingPlan =
        allPlans.find((plan) => normalizePlanName(plan?.name) === normalizePlanName(preset.name)) || null;
    }

    if (existingPlan) {
      await api.updatePlan(existingPlan.id, payload);
    } else {
      await api.createPlan(payload);
    }

    res.redirect(withAdminBase('/plans?success=Тариф+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/plans?error=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.post('/plans/:id/delete', async (req, res) => {
  res.redirect(withAdminBase('/plans?error=Удаление+тарифов+в+этом+разделе+отключено'));
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
    });
    res.redirect(withAdminBase('/proxies?success=Прокси+добавлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/proxies?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.post('/proxies/:id/update', async (req, res) => {
  try {
    await api.updateProxy(req.params.id, {
      name: req.body.name,
      proxy_url: req.body.proxy_url,
      change_ip_url: req.body.change_ip_url || null,
      is_active: req.body.is_active === 'on',
    });
    res.redirect(withAdminBase('/proxies?success=Прокси+обновлен'));
  } catch (error) {
    res.redirect(withAdminBase(`/proxies?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.post('/proxies/:id/delete', async (req, res) => {
  try {
    await api.deleteProxy(req.params.id);
    res.redirect(withAdminBase('/proxies?success=Прокси+удален'));
  } catch (error) {
    res.redirect(withAdminBase(`/proxies?success=${encodeURIComponent(`Ошибка: ${error.message}`)}`));
  }
});

router.get('/users', async (req, res) => {
  try {
    const users = await api.getUsers();
    res.render('users', { users, error: null });
  } catch (error) {
    res.render('users', { users: [], error: error.message });
  }
});

router.get('/monitorings', async (req, res) => {
  try {
    const monitorings = await api.getMonitorings();
    res.render('monitorings', { monitorings, error: null });
  } catch (error) {
    res.render('monitorings', { monitorings: [], error: error.message });
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
