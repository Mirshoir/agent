/* global window */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { createRoot } from 'react-dom/client';

import './app.css';
import './tweaks-panel.jsx';
import './data.jsx';
import './icons.jsx';

const I = window.I;
const IS_LOCALHOST = ['localhost', '127.0.0.1'].includes(window.location.hostname);

const ENV_API_BASE = import.meta.env.VITE_API_URL || 'https://agent-1-xi6h.onrender.com';
const ENV_DASHBOARD_SECRET = import.meta.env.VITE_DASHBOARD_SECRET || '';

const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('clear_auth')) {
  window.localStorage.removeItem('instaagent_dashboard_secret');
  window.localStorage.removeItem('instaagent_dashboard_auth');
  window.localStorage.removeItem('instaagent_owner_email');
  window.localStorage.removeItem('instaagent_api_base');
}
const API_BASE = (
  urlParams.get('api') ||
  window.localStorage.getItem('instaagent_api_base') ||
  ENV_API_BASE ||
  window.INSTAAGENT_API_BASE ||
  (IS_LOCALHOST ? 'http://localhost:8000' : '')
).replace(/\/$/, '');

const DASHBOARD_SECRET =
  urlParams.get('secret') ||
  (IS_LOCALHOST ? 'localdev' : '') ||
  ENV_DASHBOARD_SECRET ||
  window.localStorage.getItem('instaagent_dashboard_secret') ||
  window.INSTAAGENT_DASHBOARD_SECRET ||
  '';

if (urlParams.get('api')) window.localStorage.setItem('instaagent_api_base', API_BASE);
if (urlParams.get('secret') && DASHBOARD_SECRET !== 'YOUR_DASHBOARD_SECRET') {
  window.localStorage.setItem('instaagent_dashboard_secret', DASHBOARD_SECRET);
}
if (window.localStorage.getItem('instaagent_dashboard_secret') === 'YOUR_DASHBOARD_SECRET') {
  window.localStorage.removeItem('instaagent_dashboard_secret');
}

const OWNER_EMAIL_STORAGE_KEY = 'instaagent_owner_email';
const OWNER_EMAIL_PARAM = 'owner_email';
const DASHBOARD_AUTH_STORAGE_KEY = 'instaagent_dashboard_auth';

function normalizeOwnerEmail(value = '') {
  return String(value || '').trim().toLowerCase();
}

function ownerEmailFromUrl() {
  return normalizeOwnerEmail(
    urlParams.get(OWNER_EMAIL_PARAM) ||
    urlParams.get('owner') ||
    urlParams.get('email') ||
    ''
  );
}

function ownerEmailFromStorage() {
  return normalizeOwnerEmail(window.localStorage.getItem(OWNER_EMAIL_STORAGE_KEY) || '');
}

function resolvedOwnerEmail() {
  return ownerEmailFromUrl() || ownerEmailFromStorage() || normalizeOwnerEmail(window.INSTAAGENT_OWNER_EMAIL || '');
}

if (ownerEmailFromUrl()) {
  window.localStorage.setItem(OWNER_EMAIL_STORAGE_KEY, ownerEmailFromUrl());
}

function readAuthSession() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(DASHBOARD_AUTH_STORAGE_KEY) || '{}');
    if (!parsed || typeof parsed !== 'object') return null;
    const ownerEmail = normalizeOwnerEmail(parsed.ownerEmail);
    const token = normalizeId(parsed.token || '');
    if (!ownerEmail || !token) return null;
    return {
      ownerEmail,
      token,
      isAdmin: parsed.isAdmin === true,
      role: parsed.role || '',
      at: parsed.at || '',
    };
  } catch {
    return null;
  }
}

function saveAuthSession(ownerEmail, session = {}) {
  const clean = normalizeOwnerEmail(ownerEmail);
  if (!clean) return;
  window.localStorage.setItem(DASHBOARD_AUTH_STORAGE_KEY, JSON.stringify({
    ownerEmail: clean,
    token: session.token || '',
    isAdmin: session.isAdmin === true,
    role: session.role || '',
    at: new Date().toISOString(),
  }));
  window.localStorage.setItem(OWNER_EMAIL_STORAGE_KEY, clean);
}

function clearAuthSession({ preserveSecret = false, preserveOwner = false } = {}) {
  window.localStorage.removeItem(DASHBOARD_AUTH_STORAGE_KEY);
  if (!preserveOwner) window.localStorage.removeItem(OWNER_EMAIL_STORAGE_KEY);
  if (!preserveSecret) window.localStorage.removeItem('instaagent_dashboard_secret');
}

function scopedPath(path) {
  const ownerEmail = resolvedOwnerEmail();
  if (!ownerEmail) return path;
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}${OWNER_EMAIL_PARAM}=${encodeURIComponent(ownerEmail)}`;
}

const API = {
  async fetchWithTimeout(url, options = {}, timeoutMs = 35000) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      window.clearTimeout(timer);
    }
  },
  async get(path) {
    const res = await API.fetchWithTimeout(`${API_BASE}${scopedPath(path)}`, { headers: apiHeaders() });
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
  async post(path, params = {}) {
    const qs = new URLSearchParams(params);
    const endpoint = `${scopedPath(path)}${qs.toString() ? `${scopedPath(path).includes('?') ? '&' : '?'}${qs.toString()}` : ''}`;
    const res = await API.fetchWithTimeout(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: apiHeaders(),
    });
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
  async postJson(path, body = {}) {
    const res = await API.fetchWithTimeout(`${API_BASE}${scopedPath(path)}`, {
      method: 'POST',
      headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, owner_email: body?.owner_email || resolvedOwnerEmail() || undefined }),
    });
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
  async delete(path) {
    const res = await API.fetchWithTimeout(`${API_BASE}${scopedPath(path)}`, {
      method: 'DELETE',
      headers: apiHeaders(),
    });
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
};

const THREAD_POLL_MS = 2500;
const INBOX_POLL_MS = 6000;
const STATS_POLL_MS = 20000;
const TASKS_POLL_MS = 2500;
const AI_OVERRIDE_STORAGE_KEY = 'instaagent_ai_overrides';
const DELETED_CONVERSATIONS_STORAGE_KEY = 'instaagent_deleted_conversations';
const LEAD_STAGES_STORAGE_KEY = 'instaagent_lead_stages';
const LEAD_PRICES_STORAGE_KEY = 'instaagent_lead_prices';
const OPERATOR_DEALS_STORAGE_KEY = 'instaagent_operator_deals';
const OPERATOR_ADMIN_NOTES_STORAGE_KEY = 'instaagent_operator_admin_notes';
const USER_PROFILE_STORAGE_KEY = 'instaagent_user_profiles';
const DASHBOARD_HASH = '#dashboard';
const UI_LANG_STORAGE_KEY = 'instaagent_ui_lang';

const LANDING_PREVIEWS = [
  ['inbox', '/screenshots/inbox.png'],
  ['knowledge', '/screenshots/inbox-4.png'],
  ['prompts', '/screenshots/inbox-7.png'],
  ['insights', '/screenshots/inbox-8.png'],
  ['details', '/screenshots/02-with-wa.png'],
];

const LANDING_TEXT = {
  en: {
    appName: 'Instaagent',
    navFeatures: 'Features',
    navDashboard: 'Dashboard',
    navAiControl: 'AI Control',
    navFaq: 'FAQ',
    openDashboard: 'Open Dashboard',
    eyebrow: 'Instaagent for Milana Premium and modern sales teams',
    heroTitle: 'AI Sales Assistant for Instagram, Telegram, and WhatsApp',
    heroCopy: 'Manage all customer chats in one dashboard, let AI reply naturally, and help your sales team close more orders.',
    getStarted: 'Get Started',
    bookDemo: 'Book Demo',
    featureKicker: 'Product features',
    featureTitle: 'Everything your sales team needs to reply faster',
    features: [
      ['Unified Inbox', 'Instagram, Telegram, and WhatsApp chats in one place.'],
      ['AI Auto Replies', 'Natural short replies based on business knowledge.'],
      ['Human Takeover', 'Turn AI off for any chat and reply manually.'],
      ['AI Prompt Settings', 'Control how the assistant speaks and sells.'],
      ['Prompt Generator', 'Improve weak prompts automatically with Accept / Decline controls.'],
      ['Knowledge Base', 'Add product info, prices, delivery, FAQ, and company rules.'],
      ['Insights Dashboard', 'Track messages, platforms, customers, AI activity, and sales signals.'],
      ['Media Support', 'Receive and send images, videos, and voice messages.'],
      ['Catalog Sharing', 'Send product/catalog links quickly from chat.'],
      ['Multi-language Support', 'Uzbek, Russian, and English customer conversations.'],
    ],
    previewKicker: 'Dashboard preview',
    previewTitle: 'See the product before your team uses it',
    previewLabels: { inbox: 'Inbox', knowledge: 'Knowledge page', prompts: 'AI Prompt Settings', insights: 'Insights dashboard', details: 'Chat details panel' },
    howKicker: 'How it works',
    howTitle: 'Launch the assistant in three steps',
    steps: [
      ['Connect your channels', 'Instagram, Telegram, and WhatsApp.'],
      ['Add business knowledge', 'Products, prices, delivery, FAQ, tone, and sales rules.'],
      ['Let AI assist your team', 'AI replies naturally while your agents stay in control.'],
    ],
    aiKicker: 'AI control',
    aiTitle: 'You are always in control',
    aiCopy: 'Instaagent is built for real sales operations where agents need speed without losing judgment.',
    aiItems: ['Turn AI on/off per chat', 'Edit prompts anytime', 'Accept or decline AI prompt improvements', 'Delete or archive conversations', 'Human agents can take over instantly'],
    faqTitle: 'Common questions',
    faq: [
      ['Does it support Instagram?', 'Yes. Instaagent is designed for Instagram DMs and sales conversations.'],
      ['Does it support Telegram?', 'Yes. It supports Telegram user/private flows and bot private chats.'],
      ['Does it support WhatsApp?', 'Yes. WhatsApp conversations can be managed from the same inbox.'],
      ['Can I turn AI off?', 'Yes. Agents can pause AI per chat and take over instantly.'],
      ['Can I edit the AI prompt?', 'Yes. Prompt settings and business knowledge can be edited anytime.'],
    ],
  },
  uz: {
    appName: 'Instaagent',
    navFeatures: 'Imkoniyatlar',
    navDashboard: 'Dashboard',
    navAiControl: 'AI nazorati',
    navFaq: 'FAQ',
    openDashboard: 'Dashboardni ochish',
    eyebrow: 'Milana Premium va zamonaviy savdo jamoalari uchun Instaagent',
    heroTitle: 'Instagram, Telegram va WhatsApp uchun AI savdo yordamchisi',
    heroCopy: 'Barcha mijoz suhbatlarini bitta dashboardda boshqaring, AI tabiiy javob bersin va jamoangiz ko‘proq buyurtma yopsin.',
    getStarted: 'Boshlash',
    bookDemo: 'Demo bron qilish',
    featureKicker: 'Mahsulot imkoniyatlari',
    featureTitle: 'Savdo jamoangizga tezroq javob berish uchun hammasi bir joyda',
    features: [
      ['Yagona Inbox', 'Instagram, Telegram va WhatsApp chatlari bitta joyda.'],
      ['AI avtomatik javoblar', 'Biznes bilimlari asosida qisqa va tabiiy javoblar.'],
      ['Human takeover', 'Istalgan chatda AI ni o‘chirib, qo‘lda javob bering.'],
      ['AI Prompt sozlamalari', 'AI qanday gapirishini va sotishini boshqaring.'],
      ['Prompt generator', 'Kuchsiz promptlarni Accept/Decline bilan yaxshilang.'],
      ['Bilimlar bazasi', 'Mahsulot, narx, yetkazib berish va FAQ ni kiriting.'],
      ['Insights dashboard', 'Xabarlar, platformalar, mijozlar va AI faolligini kuzating.'],
      ['Media qo‘llab-quvvatlash', 'Rasm, video va ovozli xabarlarni yuboring/qabul qiling.'],
      ['Katalog ulashish', 'Chatdan katalog havolalarini tez yuboring.'],
      ['Ko‘p til', 'Uzbek, Rus va English suhbatlar uchun mos.'],
    ],
    previewKicker: 'Dashboard preview',
    previewTitle: 'Jamoa ishga tushirishdan oldin mahsulotni ko‘ring',
    previewLabels: { inbox: 'Inbox', knowledge: 'Bilim sahifasi', prompts: 'AI Prompt sozlamalari', insights: 'Insights dashboard', details: 'Chat tafsilotlari paneli' },
    howKicker: 'Qanday ishlaydi',
    howTitle: 'Yordamchini 3 bosqichda ishga tushiring',
    steps: [
      ['Kanallarni ulang', 'Instagram, Telegram va WhatsApp.'],
      ['Biznes bilimini kiriting', 'Mahsulot, narx, yetkazib berish, FAQ va qoidalar.'],
      ['AI ni jamoaga yordam bering', 'AI tabiiy javob beradi, nazorat esa sizda qoladi.'],
    ],
    aiKicker: 'AI nazorat',
    aiTitle: 'Nazorat har doim sizda',
    aiCopy: 'Instaagent tezlik kerak bo‘lgan real savdo jarayonlari uchun yaratilgan.',
    aiItems: ['Har chatda AI ni yoqish/o‘chirish', 'Promptlarni istalgan payt tahrirlash', 'AI prompt yaxshilanishini qabul/rad etish', 'Suhbatni o‘chirish yoki arxivlash', 'Operator darhol takeover qilishi mumkin'],
    faqTitle: 'Ko‘p so‘raladigan savollar',
    faq: [
      ['Instagram qo‘llaydimi?', 'Ha. Instaagent Instagram DM savdolariga mos.'],
      ['Telegram qo‘llaydimi?', 'Ha. Telegram private va bot chatlarini qo‘llaydi.'],
      ['WhatsApp qo‘llaydimi?', 'Ha. WhatsApp chatlari ham shu inboxda boshqariladi.'],
      ['AI ni o‘chirish mumkinmi?', 'Ha. Har chat bo‘yicha AI ni pauzaga qo‘yish mumkin.'],
      ['AI promptni tahrirlash mumkinmi?', 'Ha. Prompt va bilim bazasini xohlagan vaqtda yangilash mumkin.'],
    ],
  },
  ru: {
    appName: 'Instaagent',
    navFeatures: 'Функции',
    navDashboard: 'Дашборд',
    navAiControl: 'Контроль AI',
    navFaq: 'FAQ',
    openDashboard: 'Открыть дашборд',
    eyebrow: 'Instaagent для Milana Premium и современных отделов продаж',
    heroTitle: 'AI-ассистент продаж для Instagram, Telegram и WhatsApp',
    heroCopy: 'Управляйте чатами клиентов в одном дашборде, дайте AI отвечать естественно и помогайте команде закрывать больше заказов.',
    getStarted: 'Начать',
    bookDemo: 'Запросить демо',
    featureKicker: 'Возможности',
    featureTitle: 'Все, что нужно вашей команде продаж',
    features: [
      ['Единый Inbox', 'Instagram, Telegram и WhatsApp в одном месте.'],
      ['AI-ответы', 'Короткие и естественные ответы по базе знаний.'],
      ['Human takeover', 'Отключайте AI в любом чате и отвечайте вручную.'],
      ['Настройки AI Prompt', 'Управляйте стилем общения и продаж AI.'],
      ['Prompt generator', 'Улучшайте слабые prompt с Accept/Decline.'],
      ['База знаний', 'Добавьте товары, цены, доставку и FAQ.'],
      ['Insights dashboard', 'Отслеживайте сообщения, платформы и активность AI.'],
      ['Поддержка медиа', 'Изображения, видео и голосовые сообщения.'],
      ['Отправка каталога', 'Быстро отправляйте ссылки из чата.'],
      ['Мультиязык', 'Поддержка узбекского, русского и английского.'],
    ],
    previewKicker: 'Превью дашборда',
    previewTitle: 'Посмотрите продукт до запуска для команды',
    previewLabels: { inbox: 'Inbox', knowledge: 'Страница знаний', prompts: 'Настройки AI Prompt', insights: 'Insights dashboard', details: 'Панель деталей чата' },
    howKicker: 'Как это работает',
    howTitle: 'Запуск в 3 шага',
    steps: [
      ['Подключите каналы', 'Instagram, Telegram и WhatsApp.'],
      ['Добавьте знания бизнеса', 'Товары, цены, доставка, FAQ и правила продаж.'],
      ['AI помогает команде', 'AI отвечает естественно, а контроль остается у вас.'],
    ],
    aiKicker: 'Контроль AI',
    aiTitle: 'Контроль всегда у вас',
    aiCopy: 'Instaagent создан для реальных процессов продаж, где важны скорость и управляемость.',
    aiItems: ['Включать/выключать AI в каждом чате', 'Редактировать prompt в любое время', 'Принимать или отклонять улучшения prompt', 'Удалять или архивировать диалоги', 'Оператор может моментально перехватить чат'],
    faqTitle: 'Частые вопросы',
    faq: [
      ['Поддерживает Instagram?', 'Да. Instaagent подходит для продаж в Instagram DM.'],
      ['Поддерживает Telegram?', 'Да. Поддерживаются private/user и bot-чаты.'],
      ['Поддерживает WhatsApp?', 'Да. WhatsApp чаты доступны в том же inbox.'],
      ['Можно отключить AI?', 'Да. AI можно ставить на паузу по каждому чату.'],
      ['Можно редактировать AI prompt?', 'Да. Prompt и база знаний редактируются в любое время.'],
    ],
  },
};

function readStoredObject(key) {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

function writeStoredObject(key, value) {
  window.localStorage.setItem(key, JSON.stringify(value || {}));
}

function userIdentity(currentUser = {}) {
  return normalizeOwnerEmail(
    currentUser?.ownerEmail ||
    currentUser?.email ||
    ''
  );
}

function readUserProfile(currentUser = {}) {
  const key = userIdentity(currentUser);
  const all = readStoredObject(USER_PROFILE_STORAGE_KEY);
  const row = key ? (all[key] || {}) : {};
  const fallbackName = key ? key.split('@')[0] : 'User';
  return {
    name: String(row.name || fallbackName),
    photo: String(row.photo || ''),
  };
}

function saveUserProfile(currentUser = {}, patch = {}) {
  const key = userIdentity(currentUser);
  if (!key) return readUserProfile(currentUser);
  const all = readStoredObject(USER_PROFILE_STORAGE_KEY);
  const prev = all[key] || {};
  const next = {
    ...prev,
    ...patch,
    name: String((patch.name ?? prev.name ?? key.split('@')[0]) || key.split('@')[0]).trim(),
    photo: String((patch.photo ?? prev.photo ?? '') || ''),
  };
  all[key] = next;
  writeStoredObject(USER_PROFILE_STORAGE_KEY, all);
  return next;
}

const AI_PROVIDERS = [
  {
    id: 'mistral',
    label: 'Mistral',
    keyField: 'mistral_api_key',
    defaultModel: 'mistral-small-latest',
    models: ['mistral-small-latest', 'mistral-large-latest'],
  },
  {
    id: 'openai',
    label: 'OpenAI',
    keyField: 'openai_api_key',
    defaultModel: 'gpt-4o-mini',
    models: ['gpt-4o-mini', 'gpt-4o'],
  },
  {
    id: 'gemini',
    label: 'Gemini',
    keyField: 'gemini_api_key',
    defaultModel: 'gemini-1.5-flash',
    models: ['gemini-1.5-flash', 'gemini-1.5-pro'],
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    keyField: 'anthropic_api_key',
    defaultModel: 'claude-3-5-haiku-latest',
    models: ['claude-3-5-haiku-latest', 'claude-3-5-sonnet-latest'],
  },
];

function aiProviderForModel(model = '') {
  const value = String(model || '').toLowerCase();
  if (value.startsWith('gpt-') || value.startsWith('o1') || value.startsWith('o3') || value.startsWith('o4')) return 'openai';
  if (value.startsWith('gemini')) return 'gemini';
  if (value.startsWith('claude')) return 'anthropic';
  return 'mistral';
}

function aiProviderForBusiness(business = {}) {
  const stored = String(business.ai_provider || '').toLowerCase();
  return AI_PROVIDERS.some(provider => provider.id === stored)
    ? stored
    : aiProviderForModel(business.ai_model);
}

function apiErrorMessage(data, status) {
  const metaError = data?.meta?.error || data?.details?.error || data?.data?.error;
  const description = data?.meta?.description || data?.details?.description || metaError?.message;
  const errorCode = data?.meta?.error_code || data?.details?.error_code || metaError?.code;
  const errorSubcode = data?.meta?.error_subcode || data?.details?.error_subcode || metaError?.error_subcode || metaError?.subcode;
  if (Number(errorCode) === 10 && Number(errorSubcode) === 2534022) {
    return 'Instagram reply window is closed. Ask the customer to send a new DM first.';
  }
  if (description) return errorCode ? `${description} (${errorCode})` : description;

  const message =
    data?.message ||
    data?.error ||
    metaError ||
    data?.details?.error ||
    data?.meta?.error ||
    data?.meta?.text;

  if (typeof message === 'string') return message;
  if (message) return JSON.stringify(message);
  return `Request failed: ${status}`;
}

function apiHeaders() {
  const headers = { Accept: 'application/json' };
  const auth = readAuthSession();
  if (auth?.token) headers.Authorization = `Bearer ${auth.token}`;
  const ownerEmail = resolvedOwnerEmail();
  if (ownerEmail) headers['x-owner-email'] = ownerEmail;
  return headers;
}

function dashboardSecret() {
  const savedSecret = window.localStorage.getItem('instaagent_dashboard_secret') || DASHBOARD_SECRET;
  return savedSecret && savedSecret !== 'YOUR_DASHBOARD_SECRET' ? savedSecret : '';
}

function telegramUserMediaUrl(row) {
  if (row.media_url) return row.media_url;
  if (
    row.platform !== 'telegram' ||
    row.channel !== 'telegram_user_private' ||
    !row.media_type ||
    !row.external_message_id ||
    !row.customer_id
  ) {
    return '';
  }

  const qs = new URLSearchParams();
  const secret = dashboardSecret();
  if (secret) qs.set('token', secret);

  return `${API_BASE}/api/telegram-user-media/${encodeURIComponent(row.customer_id)}/${encodeURIComponent(row.external_message_id)}${qs.toString() ? `?${qs.toString()}` : ''}`;
}

function withMediaToken(url) {
  if (!url) return '';
  const secret = dashboardSecret();
  if (!secret || !url.includes('/api/whatsapp/media/')) return url;

  try {
    const parsed = new URL(url, window.location.href);
    if (!parsed.searchParams.has('token')) parsed.searchParams.set('token', secret);
    return parsed.toString();
  } catch (e) {
    return url;
  }
}

function unwrapMetaRedirectUrl(url) {
  const value = String(url || '').trim();
  if (!value) return '';
  try {
    const parsed = new URL(value, window.location.origin);
    const host = String(parsed.hostname || '').toLowerCase();
    if (host.endsWith('instagram.com') || host.endsWith('facebook.com')) {
      const target = parsed.searchParams.get('u');
      if (target && /^https?:\/\//i.test(target)) return decodeURIComponent(target);
    }
  } catch (e) {
    return value;
  }
  return value;
}

function isInstagramPostLink(url) {
  const value = String(url || '').toLowerCase();
  return /^https?:\/\//.test(value) && value.includes('instagram.com/') && (
    value.includes('/p/') ||
    value.includes('/reel/') ||
    value.includes('/tv/') ||
    value.includes('/share/')
  );
}

function isPlayableVideoUrl(url) {
  const value = String(url || '').toLowerCase();
  return /^https?:\/\//.test(value) && !isInstagramPostLink(value) && (
    /\.(mp4|mov|m4v|webm)(\?|$)/i.test(value) ||
    value.includes('cdninstagram.com') ||
    value.includes('fbcdn.net') ||
    value.includes('lookaside.fbsbx.com')
  );
}

function isRenderableImageUrl(url) {
  const value = String(url || '').toLowerCase();
  return /^https?:\/\//.test(value) && !isInstagramPostLink(value) && /\.(png|jpe?g|webp|gif)(\?|$)/i.test(value);
}

function resolveForwardedPostLink(row = {}) {
  const payload = row.raw_payload || {};
  const msg = payload.message || {};
  const shares = Array.isArray(msg.shares) ? msg.shares : [];
  const attachments = Array.isArray(msg.attachments) ? msg.attachments : [];

  const candidates = [
    row.post_permalink,
    row.postPermalink,
    payload.post_permalink,
    payload.postPermalink,
    msg.permalink,
    msg.link,
    row.media_url,
    row.mediaUrl,
  ];

  shares.forEach((share) => {
    if (!share || typeof share !== 'object') return;
    candidates.push(share.link, share.url, share.permalink);
  });

  attachments.forEach((att) => {
    if (!att || typeof att !== 'object') return;
    const p = att.payload || {};
    candidates.push(p.url, p.link, p.permalink, p.external_url);
  });

  let fallback = '';
  for (const raw of candidates) {
    const url = String(raw || '').trim();
    if (!/^https?:\/\//i.test(url)) continue;
    const unwrapped = unwrapMetaRedirectUrl(url);
    if (!fallback) fallback = unwrapped || url;
    if (isInstagramPostLink(unwrapped) || isInstagramPostLink(url)) return unwrapped || url;
  }
  return fallback;
}

function businessOwnerEmail(business = {}) {
  return normalizeOwnerEmail(
    business.owner_email ||
    business.business_owner_email ||
    business.user_email ||
    business.email ||
    ''
  );
}

function conversationOwnerEmail(row = {}) {
  return normalizeOwnerEmail(
    row.owner_email ||
    row.business_owner_email ||
    row.user_email ||
    row.email ||
    ''
  );
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error('Could not read file'));
    reader.readAsDataURL(file);
  });
}

function recordingMimeType() {
  if (!window.MediaRecorder) return '';
  const types = [
    'audio/ogg;codecs=opus',
    'audio/ogg',
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
  ];
  return types.find(type => window.MediaRecorder.isTypeSupported?.(type)) || '';
}

function extensionForMime(mimeType) {
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('mp4')) return 'm4a';
  if (mimeType.includes('mpeg')) return 'mp3';
  return 'webm';
}

function formatRecordTime(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, '0');
  return `${minutes}:${seconds}`;
}

const EMOJI_SETS = [
  { label: 'Smileys', items: '😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 🙃 😉 😌 😍 🥰 😘 😗 😙 😚 😋 😛 😝 😜 🤪 🤨 🧐 🤓 😎 🥳 😏 😒 😞 😔 😟 😕 🙁 ☹️ 😣 😖 😫 😩 🥺 😢 😭 😤 😠 😡 🤬 🤯 😳 🥵 🥶 😱 😨 😰 😥 😓 🤗 🤔 🤭 🤫 🤥 😶 😐 😑 😬 🙄 😯 😦 😧 😮 😲 🥱 😴 🤤 😪 😵 🤐 🥴 🤢 🤮 🤧 😷 🤒 🤕'.split(' ') },
  { label: 'Hands', items: '👋 🤚 🖐️ ✋ 🖖 👌 🤌 🤏 ✌️ 🤞 🫰 🤟 🤘 🤙 👈 👉 👆 🖕 👇 ☝️ 👍 👎 ✊ 👊 🤛 🤜 👏 🙌 👐 🤲 🤝 🙏 ✍️ 💅 🤳 💪 🦾'.split(' ') },
  { label: 'Hearts', items: '❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💟 💌 💋 💯 ✨ ⭐ 🌟 💫 🔥 🎉 🎊 🎁 🏆'.split(' ') },
  { label: 'People', items: '👶 🧒 👦 👧 🧑 👨 👩 🧔 👴 👵 🙍 🙎 🙅 🙆 💁 🙋 🧏 🙇 🤦 🤷 👮 🕵️ 💂 👷 🤴 👸 👳 👲 🧕 🤵 👰 🤰 🤱 🧑‍💼 🧑‍💻 🧑‍🔧 🧑‍🎨 🧑‍🚀'.split(' ') },
  { label: 'Objects', items: '📦 🛍️ 👜 👗 👚 👕 👖 🧥 👟 👠 👢 👑 💍 💄 🧴 🧵 🪡 📱 💻 ⌚ 📷 🎥 🎤 🎧 📞 💳 💵 🧾 📝 📌 📍 🔐 🔑'.split(' ') },
  { label: 'Symbols', items: '✅ ❌ ❗ ❓ ⁉️ ⚠️ 🚫 🔴 🟠 🟡 🟢 🔵 🟣 ⚫ ⚪ 🟤 ⬆️ ⬇️ ⬅️ ➡️ 🔁 🔄 🆕 🆗 🆒 🆘 💲 #️⃣ *️⃣ 0️⃣ 1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣ 8️⃣ 9️⃣'.split(' ') },
];

function LandingPage({ onOpenDashboard, lang, setLang }) {
  const l = LANDING_TEXT[lang] || LANDING_TEXT.en;
  return (
    <main className="landing-page">
      <nav className="landing-nav">
        <a className="landing-brand" href="#top">
          <span>{l.appName}</span>
        </a>
        <div className="landing-links">
          <a href="#features">{l.navFeatures}</a>
          <a href="#preview">{l.navDashboard}</a>
          <a href="#control">{l.navAiControl}</a>
          <a href="#faq">{l.navFaq}</a>
        </div>
        <div className="lang">
          {['en', 'uz', 'ru'].map(code => (
            <button key={code} className={lang === code ? 'on' : ''} onClick={() => setLang(code)}>{code}</button>
          ))}
        </div>
        <button onClick={onOpenDashboard}>{l.openDashboard}</button>
      </nav>

      <section id="top" className="landing-hero">
        <div className="landing-hero-inner">
          <p className="eyebrow">{l.eyebrow}</p>
          <h1>{l.heroTitle}</h1>
          <p className="hero-copy">{l.heroCopy}</p>
          <div className="hero-actions">
            <button onClick={onOpenDashboard}>{l.getStarted}</button>
            <button className="secondary" onClick={onOpenDashboard}>{l.openDashboard}</button>
            <a href="mailto:hello@instaagent.ai?subject=Book%20Instaagent%20Demo">{l.bookDemo}</a>
          </div>
        </div>
      </section>

      <section id="features" className="landing-section">
        <div className="section-kicker">{l.featureKicker}</div>
        <h2>{l.featureTitle}</h2>
        <div className="feature-grid">
          {l.features.map(([title, text]) => (
            <article className="feature-card" key={title}>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="preview" className="landing-section preview-section">
        <div className="section-kicker">{l.previewKicker}</div>
        <h2>{l.previewTitle}</h2>
        <div className="preview-grid">
          {LANDING_PREVIEWS.map(([key, src], index) => (
            <figure className={`preview-card ${index === 0 ? 'wide' : ''}`} key={key}>
              <img src={src} alt={`${l.previewLabels[key]} dashboard preview`} />
              <figcaption>{l.previewLabels[key]}</figcaption>
            </figure>
          ))}
        </div>
      </section>

      <section className="landing-section how-section">
        <div className="section-kicker">{l.howKicker}</div>
        <h2>{l.howTitle}</h2>
        <div className="steps-grid">
          {l.steps.map((item, idx) => (
            <article key={item[0]}><b>{idx + 1}</b><h3>{item[0]}</h3><p>{item[1]}</p></article>
          ))}
        </div>
      </section>

      <section id="control" className="landing-split">
        <div>
          <div className="section-kicker">{l.aiKicker}</div>
          <h2>{l.aiTitle}</h2>
          <p>{l.aiCopy}</p>
        </div>
        <ul>
          {l.aiItems.map(item => <li key={item}>{item}</li>)}
        </ul>
      </section>

      <section className="landing-section usecase-section">
        <div className="usecase-panel problem">
          <div className="section-kicker">Problem</div>
          <h2>Customers message from many platforms. Replies are slow, repeated, and hard to track.</h2>
        </div>
        <div className="usecase-panel solution">
          <div className="section-kicker">Solution</div>
          <h2>Instaagent organizes every message and helps your team respond faster with natural AI replies.</h2>
        </div>
      </section>

      <section className="landing-section">
        <div className="section-kicker">Business use cases</div>
        <h2>Built for textile sales, boutiques, wholesale, and export teams</h2>
        <p className="landing-lead">Perfect for:</p>
        <div className="usecase-grid">
          {['Textile shops', 'Instagram boutiques', 'Wholesale sellers', 'Online stores', 'Export businesses', 'Sales teams'].map(item => <span key={item}>{item}</span>)}
        </div>
        <div className="textile-list">
          {['Catalog requests', 'Wholesale questions', 'Product availability', 'Delivery questions', 'Price inquiries', 'Customer follow-up'].map(item => <span key={item}>{item}</span>)}
        </div>
      </section>

      <section className="landing-section insights-preview">
        <div className="section-kicker">Insights preview</div>
        <h2>Know what is happening across every channel</h2>
        <div className="insight-pill-grid">
          {['Total conversations', 'New leads', 'AI handled chats', 'Human takeover chats', 'Messages by platform', 'Most requested products', 'Average response time', 'Unread messages'].map(item => <span key={item}>{item}</span>)}
        </div>
      </section>

      <section className="landing-split safety-section">
        <div>
          <div className="section-kicker">Trust and safety</div>
          <h2>Safe for business use</h2>
          <p>AI follows the facts your company provides and leaves final control with your team.</p>
        </div>
        <ul>
          <li>AI does not invent prices</li>
          <li>AI follows your business knowledge</li>
          <li>Agents can disable AI anytime</li>
          <li>Human review is always possible</li>
          <li>Customer data stays in your dashboard</li>
        </ul>
      </section>

      <section id="faq" className="landing-section faq-section">
        <div className="section-kicker">{l.navFaq}</div>
        <h2>{l.faqTitle}</h2>
        <div className="faq-grid">
          {l.faq.map(([question, answer]) => (
            <details key={question}>
              <summary>{question}</summary>
              <p>{answer}</p>
            </details>
          ))}
        </div>
      </section>

      <footer className="landing-footer">
        <div>
          <strong>Instaagent</strong>
          <p>AI sales assistant for Instagram, Telegram, and WhatsApp.</p>
        </div>
        <nav>
          <a href="#features">Product links</a>
          <a href="mailto:hello@instaagent.ai">Contact</a>
          <a href="#privacy">Privacy Policy</a>
          <a href="#terms">Terms of Service</a>
          <a href="#data-deletion">Data Deletion Instructions</a>
          <button onClick={onOpenDashboard}>Dashboard link</button>
        </nav>
      </footer>
    </main>
  );
}

function SignInPage({ lang, onSignedIn, onBack }) {
  const l = LANDING_TEXT[lang] || LANDING_TEXT.en;
  const [mode, setMode] = useState('signin');
  const [email, setEmail] = useState(resolvedOwnerEmail());
  const [secret, setSecret] = useState('');
  const [signUpRole, setSignUpRole] = useState('operator');
  const [businessId, setBusinessId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const submitSignIn = async (e) => {
    e.preventDefault();
    const ownerEmail = normalizeOwnerEmail(email);
    const cleanSecret = String(secret || '').trim();
    if (!ownerEmail) {
      setError('Email is required.');
      return;
    }
    if (!cleanSecret) {
      setError('Password is required.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const login = await API.postJson('/api/v2/auth/login', {
        email: ownerEmail,
        password: cleanSecret,
      });
      const payload = login.data || {};
      if (!payload.token) throw new Error('Missing auth token.');
      window.localStorage.setItem(OWNER_EMAIL_STORAGE_KEY, ownerEmail);
      saveAuthSession(ownerEmail, {
        token: payload.token,
        isAdmin: payload.user?.is_admin === true,
        role: payload.user?.role || '',
      });
      onSignedIn({
        ownerEmail,
        token: payload.token,
        isAdmin: payload.user?.is_admin === true,
        role: payload.user?.role || '',
      });
    } catch (err) {
      setError(err.message || 'Sign in failed.');
      clearAuthSession();
    } finally {
      setLoading(false);
    }
  };

  const submitSignUp = async (e) => {
    e.preventDefault();
    const cleanEmail = normalizeOwnerEmail(email);
    const cleanSecret = String(secret || '').trim();
    const cleanBusiness = String(businessId || '').trim();
    if (!cleanEmail) {
      setError('ID/Email is required.');
      return;
    }
    if (!cleanSecret || cleanSecret.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }
    if (signUpRole === 'operator' && !cleanBusiness) {
      setError('Business ID is required for operator sign-up.');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const signup = await API.postJson('/api/v2/auth/signup', {
        email: cleanEmail,
        password: cleanSecret,
        role: signUpRole,
        business_id: signUpRole === 'operator' ? cleanBusiness : '',
      });
      const payload = signup.data || {};
      window.localStorage.setItem(OWNER_EMAIL_STORAGE_KEY, cleanEmail);
      saveAuthSession(cleanEmail, {
        token: payload.token || '',
        isAdmin: payload.user?.is_admin === true,
        role: payload.user?.role || signUpRole,
      });
      onSignedIn({
        ownerEmail: cleanEmail,
        token: payload.token || '',
        isAdmin: payload.user?.is_admin === true,
        role: payload.user?.role || signUpRole,
      });
    } catch (err) {
      setError(err.message || 'Sign up failed.');
      clearAuthSession();
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="signin-shell">
      <section className="signin-card">
        <h1>{l.appName} Access</h1>
        <p>{mode === 'signin' ? 'Sign in with your assigned account.' : 'Create a separate admin or operator account.'}</p>
        <div className="operators-mode-switch" style={{ marginBottom: 12 }}>
          <button type="button" className={mode === 'signin' ? 'active' : ''} onClick={() => { setMode('signin'); setError(''); }}>Sign In</button>
          <button type="button" className={mode === 'signup' ? 'active' : ''} onClick={() => { setMode('signup'); setError(''); }}>Sign Up</button>
        </div>
        <form onSubmit={mode === 'signin' ? submitSignIn : submitSignUp}>
          <label>
            <span>ID / Email</span>
            <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="operator@company.com" autoComplete="username" />
          </label>
          <label>
            <span>Password</span>
            <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="Minimum 6 characters" autoComplete="current-password" />
          </label>
          {mode === 'signup' && (
            <label>
              <span>Account type</span>
              <select value={signUpRole} onChange={(e) => setSignUpRole(e.target.value)}>
                <option value="operator">Operator</option>
                <option value="admin">Admin</option>
              </select>
            </label>
          )}
          {mode === 'signup' && signUpRole === 'operator' && (
            <label>
              <span>Business ID</span>
              <input value={businessId} onChange={(e) => setBusinessId(e.target.value)} placeholder="87963381-aa63-47f1-a55e-858dc821b52f" />
            </label>
          )}
          {error && <div className="signin-error">{error}</div>}
          <div className="signin-actions">
            <button type="submit" disabled={loading}>{loading ? (mode === 'signin' ? 'Signing in...' : 'Signing up...') : (mode === 'signin' ? 'Sign In' : 'Sign Up')}</button>
            <button type="button" className="ghost" onClick={onBack}>Back</button>
          </div>
        </form>
      </section>
    </main>
  );
}

function hashHue(value) {
  let hash = 0;
  for (const ch of String(value || 'client')) hash = ((hash << 5) - hash) + ch.charCodeAt(0);
  return Math.abs(hash) % 360;
}

function initialsFromName(name = '') {
  const clean = String(name || '').trim();
  if (!clean) return 'U';
  const parts = clean.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase();
  return `${parts[0][0] || ''}${parts[1][0] || ''}`.toUpperCase();
}

function initials(name) {
  const parts = String(name || 'Client').trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] || 'C') + (parts[1]?.[0] || parts[0]?.[1] || '');
}

function avatarFor(name, id) {
  const hue = hashHue(`${name}:${id}`);
  return {
    initials: initials(name).toUpperCase(),
    color: `linear-gradient(135deg, oklch(72% 0.11 ${hue}), oklch(48% 0.13 ${(hue + 34) % 360}))`,
  };
}

function formatPhone(value) {
  const raw = String(value || '').replace(/[^\d+]/g, '');
  if (!raw) return '';
  const digits = raw.replace(/\D/g, '');
  if (digits.length === 12 && digits.startsWith('998')) {
    return `+998 ${digits.slice(3, 5)} ${digits.slice(5, 8)} ${digits.slice(8, 10)} ${digits.slice(10)}`;
  }
  return raw.startsWith('+') ? raw : `+${raw}`;
}

function platformHandle(row) {
  if (row.platform === 'whatsapp') return formatPhone(row.customer_id || row.chat_id);
  if (row.platform === 'telegram') {
    const username = String(row.customer_name || '').match(/\(@([^)]+)\)/)?.[1];
    if (username) return `@${username}`;
    return row.customer_name?.startsWith('@') ? row.customer_name : `@${row.customer_name || row.customer_id}`;
  }
  return row.customer_name?.startsWith('@') ? row.customer_name : `@${row.customer_id || row.customer_name || 'instagram'}`;
}

function channelLabel(platform, channel) {
  if (platform === 'telegram') {
    if (channel === 'telegram_user_private') return 'User account';
    if (channel === 'telegram_bot_group') return 'Bot group';
    if (channel === 'telegram_bot_private' || channel === 'private') return 'Bot DM';
    return channel || 'Telegram';
  }
  if (platform === 'instagram') return channel === 'dm' || !channel ? 'Instagram DM' : channel;
  if (platform === 'whatsapp') return channel === 'whatsapp' || channel === 'whatsapp_cloud' || !channel ? 'WhatsApp' : channel;
  return channel || 'Inbox';
}

function sendRouteFor(conv) {
  if (conv.platform === 'instagram') return 'Instagram DM API';
  if (conv.platform === 'whatsapp') return 'WhatsApp Cloud API';
  if (conv.platform === 'telegram' && conv.channel === 'telegram_user_private') return 'Telegram user client';
  if (conv.platform === 'telegram') return 'Telegram bot API';
  return 'Backend API';
}

function formatRelative(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const diff = Date.now() - date.getTime();
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return 'now';
  if (diff < hour) return `${Math.max(1, Math.floor(diff / minute))} min`;
  if (diff < day) return `${Math.floor(diff / hour)} hr`;
  if (diff < 2 * day) return 'yesterday';
  return `${Math.floor(diff / day)} days`;
}

function formatClock(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatDay(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return 'Today';
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function getWhatsAppMediaId(row) {
  const raw = row.raw_payload || {};
  const kind = row.media_type;
  if (kind === 'photo') return raw.image?.id || '';
  if (kind === 'video') return raw.video?.id || '';
  if (kind === 'voice') return raw.audio?.id || '';
  if (kind === 'file') return raw.document?.id || '';
  return '';
}

function getMediaLabel(row) {
  const media = row.media_type || 'attachment';
  const source = row.platform === 'whatsapp' ? getWhatsAppMediaId(row) : row.media_file_id;
  if (row.media_url || telegramUserMediaUrl(row)) return `${media} · open media`;
  if (source) return `${media} · id ${String(source).slice(0, 10)}...`;
  return `${media} · no preview`;
}

function normalizeConversation(row) {
  const parts = String(row.id || '').split('::');
  const parsedPlatform = parts[0] || '';
  const parsedBusinessId = parts[1] || '';
  const parsedChannel = parts[2] || '';
  const parsedCustomerId = parts[3] || '';
  const customerId = row.customer_id || parsedCustomerId;
  const chatId = row.chat_id || customerId;
  const name = row.customer_name || row.name || `Client ${String(customerId || '').slice(-4)}`;
  const unread = Number(row.unread_count ?? row.unread ?? 0);
  const total = Number(row.total_messages ?? row.kpis?.orders ?? 0);
  const platform = row.platform || 'instagram';
  const channel = row.channel || parsedChannel || '';
  const channelName = row.channelName || channelLabel(platform || parsedPlatform, channel);
  const isCommentThread = Boolean(row.isCommentThread || (platform === 'instagram' && String(channel).toLowerCase().includes('comment')));
  const lastAt = row.last_message_at || row.created_at || row.lastAt || '';
  return {
    id: row.id,
    apiId: row.id,
    businessId: row.business_id || row.businessId || parsedBusinessId,
    customerId,
    chatId,
    channel,
    channelName,
    isCommentThread,
    postId: row.postId || row.post_id || '',
    postPermalink: row.postPermalink || row.post_permalink || '',
    postImageUrl: row.postImageUrl || row.post_image_url || '',
    postMediaType: (row.postMediaType || row.post_media_type || '').toLowerCase(),
    name,
    handle: row.handle || platformHandle({ ...row, customer_id: customerId, chat_id: chatId }),
    platform: platform || parsedPlatform,
    avatar: avatarFor(name, customerId),
    online: false,
    needsHuman: row.needsHuman ?? (unread > 0),
    aiOn: row.aiOn ?? (unread === 0),
    unread,
    lastTime: row.lastTime || formatRelative(lastAt),
    lastFromMe: false,
    preview: row.last_message || row.preview || 'No message preview',
    tags: [platform, channelName].filter(Boolean),
    customerSince: row.customerSince || 'first message',
    location: row.location || channelName,
    summary: row.summary || `${total || 1} saved message${total === 1 ? '' : 's'} in this ${channelName} conversation. Replies send through ${sendRouteFor({ platform, channel })}.`,
    kpis: row.kpis || { orders: total, ltv: String(unread), last: formatRelative(lastAt) || '—', conv: unread ? `${unread} unread` : 'read' },
    orders: row.orders || [],
    suggestions: row.suggestions || [],
  };
}

function clearConversationUnread(conv) {
  return {
    ...conv,
    unread: 0,
    needsHuman: false,
    kpis: {
      ...(conv.kpis || {}),
      ltv: '0',
      conv: 'read',
    },
  };
}

function normalizeMessage(row, index) {
  const inbound = row.direction === 'inbound' || row.role === 'user' || row.side === 'in' || row.side === 'inbound';
  const media = row.media_type || row.mediaKind || (row.type === 'media' ? row.label : '');
  const text = row.content || row.text || row.mediaCaption || '';
  let type = 'text';
  if (row.type === 'voice' || media === 'voice' || media === 'audio') type = 'voice';
  else if (row.type === 'media' || media) type = 'media';
  else if (text.includes('[Catalog button sent]')) type = 'catalog';

  const message = {
    id: row.id || row.external_message_id || `api-${index}`,
    day: row.day || formatDay(row.created_at),
    side: inbound ? 'inbound' : 'outbound',
    from: row.role === 'assistant' ? 'ai' : '',
    type,
    time: row.time || formatClock(row.created_at),
    text,
    mediaKind: media || '',
    mediaUrl: withMediaToken(row.media_url || row.mediaUrl || telegramUserMediaUrl(row)),
    forwardLink: resolveForwardedPostLink(row),
    mediaFileId: row.media_file_id || getWhatsAppMediaId(row),
    commentId: String(row.external_message_id || row.comment_id || row.raw_payload?.id || '').trim(),
    raw: row,
  };

  if (type === 'catalog') {
    message.catalogText = text.replace('[Catalog button sent]', '').trim() || 'Catalog sent.';
    message.catalogLabel = 'Open catalog';
  }

  if (type === 'media') {
    message.label = getMediaLabel(row);
    message.mediaCaption = text;
  }

  if (type === 'voice') {
    message.duration = text.match(/\((\d+)s\)/)?.[1] ? `0:${text.match(/\((\d+)s\)/)[1].padStart(2, '0')}` : '';
  }

  return message;
}

function resolveCommentPostPreview(conv, messages = []) {
  const base = {
    postId: conv?.postId || '',
    postPermalink: conv?.postPermalink || '',
    postImageUrl: conv?.postImageUrl || '',
    postMediaType: (conv?.postMediaType || '').toLowerCase(),
  };

  if (base.postImageUrl && (base.postPermalink || base.postId)) return base;

  for (const m of messages || []) {
    const raw = m?.raw || {};
    const payload = raw.raw_payload || {};
    const media = payload.media || {};
    const postImageUrl = raw.post_image_url || raw.postImageUrl || payload.post_image_url || '';
    const postPermalink = raw.post_permalink || raw.postPermalink || payload.post_permalink || '';
    const postMediaType = String(raw.post_media_type || raw.postMediaType || payload.post_media_type || '').toLowerCase();
    const postId = raw.post_id || raw.postId || payload.post_id || payload.media_id || media.id || '';
    if (postImageUrl || postPermalink || postId || postMediaType) {
      return { postId, postPermalink, postImageUrl, postMediaType };
    }
  }

  return base;
}

function isVideoPostPreview(post = {}) {
  const type = String(post?.postMediaType || '').toLowerCase();
  if (type.includes('video') || type.includes('reel')) return true;
  const url = String(post?.postImageUrl || '').toLowerCase();
  return /\.(mp4|mov|m4v|webm)(\?|$)/i.test(url);
}

// ---------- Small helpers ----------
function Avatar({ data, size = 38, platform, online }) {
  const style = { width: size, height: size, background: data.color, fontSize: size * 0.36 };
  return (
    <div className="avatar" style={style}>
      <span>{data.initials}</span>
      {platform === 'instagram' && (
        <span className="plat ig"><I.Inst /></span>
      )}
      {platform === 'telegram' && (
        <span className="plat tg"><I.Tg /></span>
      )}
      {platform === 'whatsapp' && (
        <span className="plat wa"><I.Wa /></span>
      )}
    </div>
  );
}

function PlatformDot({ p }) {
  if (p === 'instagram') return <span className="pdot ig" />;
  if (p === 'telegram') return <span className="pdot tg" />;
  if (p === 'whatsapp') return <span className="pdot wa" />;
  return null;
}

function PlatformIcon({ p }) {
  if (p === 'instagram') return <I.Inst />;
  if (p === 'telegram') return <I.Tg />;
  if (p === 'whatsapp') return <I.Wa />;
  return null;
}

function Toast({ message }) {
  if (!message) return null;
  return <div className="toast">{message}</div>;
}

function ToggleRow({ label, hint, checked, onChange, w = WORKSPACE_TEXT.en }) {
  return (
    <div className="toggle-row">
      <div>
        <strong>{label}</strong>
        {hint && <span>{hint}</span>}
      </div>
      <button className={`ai-toggle ${checked ? 'on' : ''}`} onClick={() => onChange(!checked)}>
        <span className="switch" />
        <span className="label-i">{checked ? (w.on || 'On') : (w.off || 'Off')}</span>
      </button>
    </div>
  );
}

function SecretField({ business, provider, onBusinessSetting, w = WORKSPACE_TEXT.en }) {
  const [value, setValue] = useState('');
  const savedPreview = String(business[provider.keyField] || '').trim();

  useEffect(() => {
    setValue('');
  }, [business.id, provider.keyField]);

  const save = () => {
    const clean = value.trim();
    if (!clean || !business.id) return;
    onBusinessSetting(business.id, { [provider.keyField]: clean }, true);
    setValue('');
  };

  const clear = () => {
    if (!business.id) return;
    setValue('');
    onBusinessSetting(business.id, { [provider.keyField]: '' }, true);
  };

  return (
    <div className="secret-row">
      <label className="field-row">
        <span>{provider.label} {w.key}</span>
        <input
          type="password"
          value={value}
          placeholder={savedPreview ? `${w.saved} (${savedPreview})` : w.pasteApiKey}
          onChange={(e) => setValue(e.target.value)}
          onBlur={save}
          autoComplete="off"
        />
      </label>
      <button type="button" className="panel-btn subtle" disabled={!savedPreview} onClick={clear}>{w.clear}</button>
    </div>
  );
}

function PromptField({ label, value, rows = 5, onChange }) {
  return (
    <label className="field-row prompt-row">
      <span>{label}</span>
      <textarea value={value || ''} onChange={(event) => onChange(event.target.value)} rows={rows} />
    </label>
  );
}

const PROMPT_FIELD_LABELS = {
  global_prompt: 'Global prompt',
  instagram_prompt: 'Instagram rules',
  telegram_prompt: 'Telegram rules',
  whatsapp_prompt: 'WhatsApp rules',
  opening_message: 'Opening message',
  lead_collection_rules: 'Lead collection rules',
  sales_rules: 'Follow-up style',
  handoff_rules: 'Human handoff rules',
};

const WORKSPACE_TEXT = {
  en: {
    workspace: 'Workspace', leadsTitle: 'Leads Pipeline', promptsTitle: 'AI Prompt Settings', profile: 'Profile', refresh: 'Refresh', liveWorkspace: 'Live backend workspace',
    totalConversations: 'Total conversations', activeThreads: 'Active inbox threads', newLeads: 'New leads', recentProspects: 'Recent or unread prospects',
    aiHandledChats: 'AI handled chats', coveredByAi: 'Currently covered by AI', humanTakeoverChats: 'Human takeover chats', manualAttention: 'Needs manual attention',
    unreadMessages: 'Unread messages', waitingMessages: 'Customer messages waiting', responseRate: 'Response rate', estimatedInbox: 'Estimated from inbox state',
    avgResponseTime: 'Avg response time', liveEstimate: 'Live estimate', platformMessages: 'Platform messages', allPlatforms: 'Instagram + Telegram + WhatsApp',
    inbound: 'Inbound', outbound: 'Outbound', aiReplies: 'AI replies', humanReplies: 'Human replies', messagesByDay: 'Messages by day',
    messagesByPlatform: 'Messages by platform', inboundVsOutbound: 'Inbound vs outbound', aiVsHuman: 'AI replies vs human replies',
    topCustomers: 'Top active customers', noCustomers: 'No customers yet', peakHours: 'Peak messaging hours', mostProducts: 'Most mentioned products',
    productIntent: 'Catalog/product intent', priceQuestions: 'Customers asking for price', priceHint: 'Pricing questions',
    deliveryQuestions: 'Customers asking for delivery', deliveryHint: 'Delivery questions', readyToOrder: 'Customers ready to order',
    buyingIntent: 'Buying intent', followUp: 'Needs human follow-up', aiPaused: 'Takeover or AI paused',
    globalPrompt: 'Global Prompt', usedBy: 'Used by Instagram + Telegram + WhatsApp', platformOverrides: 'Platform Overrides',
    instagramRules: 'Instagram rules', telegramRules: 'Telegram rules', whatsappRules: 'WhatsApp rules', businessKnowledge: 'Business Knowledge',
    knowledgeHint: 'Products, prices, delivery, FAQ, contacts, and catalog links are managed in the Knowledge page and injected into the final prompt automatically.',
    products: 'Products', prices: 'Prices', delivery: 'Delivery', faq: 'FAQ', contacts: 'Contacts', catalogLinks: 'Catalog links',
    salesBehavior: 'Sales Behavior', openingMessage: 'Opening message', leadCollectionRules: 'Lead collection rules',
    followUpStyle: 'Follow-up style', humanHandoffRules: 'Human handoff rules', improvePrompt: 'Improve Prompt', improving: 'Improving...',
    regenerate: 'Regenerate', generatedSuggestion: 'Generated suggestion', suggestionFallback: 'Made it clearer, safer, and easier for agents to maintain.',
    acceptSuggestion: 'Accept suggestion', decline: 'Decline', savePromptSettings: 'Save AI prompt settings', saving: 'Saving...',
    promptFormula: 'Prompt formula', noBusinesses: 'No businesses returned from the backend.', connectInstagram: 'Connect Instagram', connectFacebook: 'Connect Facebook',
    unnamedBusiness: 'Unnamed business', active: 'active', paused: 'paused', botEnabled: 'Bot enabled', botEnabledHint: 'Controls automatic replies for this business.',
    instagramDms: 'Instagram DMs', instagramDmsHint: 'Automatic Instagram direct-message replies.', instagramComments: 'Instagram comments',
    instagramCommentsHint: 'Automatic comment replies.', language: 'Language', tone: 'Tone', aiModel: 'AI model', provider: 'Provider', model: 'Model',
    customModel: 'Custom model', temperature: 'Temperature', maxTokens: 'Max tokens', apiKeys: 'API keys', key: 'key', saved: 'Saved', pasteApiKey: 'Paste API key',
    clear: 'Clear', promptReady: 'Prompt suggestion ready', promptLocal: 'Prompt suggestion generated locally', noBusinessLocal: 'Generated locally because no live business is selected.',
    backendUnavailableLocal: 'Generated locally because the backend endpoint is not available yet.',
    leadNew: 'New', leadQualified: 'Qualified', leadNegotiation: 'Negotiation', leadWon: 'Won', leadLost: 'Lost',
    leadAmount: 'Potential value', leadSource: 'Source', leadUpdated: 'Updated', leadEmpty: 'No leads in this stage yet.',
    leadOpen: 'Open chat', leadPrice: 'Price', leadPricePlaceholder: 'Add price', leadPriceClear: 'Clear price',
    clientsTitle: 'Clients table', clientsSubtitle: 'All customers with status, channel, price, and last message.', clientsEmpty: 'No clients yet.',
    client: 'Client', lastMessage: 'Last message', status: 'Status', channel: 'Channel',
    operatorsTitle: 'Operators panel', operatorsSubtitle: 'Operator workspace for tasks, client messages, and leads.',
    textToOperators: 'Text to operators', textToOperatorsPlaceholder: 'Write task for operators...', saveAdminNote: 'Send task',
    adminNotes: 'Tasks history', noAdminNotes: 'No tasks yet.', messagesFromClients: 'Messages from clients',
    tasksFromAdmin: 'Tasks from admin', noTasksForYou: 'No tasks assigned to you.',
    assignOne: 'Assign one', assignGroup: 'Assign group', assignAll: 'All operators',
    operatorRanking: 'Operators ranking', successfulDeals: 'Successful deals', operatorPanel: 'Operator panel', adminPanel: 'Admin panel',
    operatorAccounts: 'Operator accounts', operatorAccountsHint: 'Create operator logins for this business.', operatorId: 'Operator ID', operatorPassword: 'Password',
    addOperator: 'Add operator', noOperators: 'No operators yet.',
  },
  uz: {
    workspace: 'Ish maydoni', leadsTitle: 'Lidlar pipeline', promptsTitle: 'AI Prompt sozlamalari', profile: 'Profil', refresh: 'Yangilash', liveWorkspace: 'Live backend ish maydoni',
    totalConversations: 'Jami suhbatlar', activeThreads: 'Faol inbox suhbatlari', newLeads: 'Yangi leadlar', recentProspects: 'Yangi yoki o‘qilmagan mijozlar',
    aiHandledChats: 'AI yuritgan chatlar', coveredByAi: 'AI nazoratida', humanTakeoverChats: 'Operatorga o‘tgan chatlar', manualAttention: 'Qo‘lda ko‘rish kerak',
    unreadMessages: 'O‘qilmagan xabarlar', waitingMessages: 'Javob kutayotgan xabarlar', responseRate: 'Javob darajasi', estimatedInbox: 'Inbox holatidan taxmin',
    avgResponseTime: 'O‘rtacha javob vaqti', liveEstimate: 'Live taxmin', platformMessages: 'Platforma xabarlari', allPlatforms: 'Instagram + Telegram + WhatsApp',
    inbound: 'Kiruvchi', outbound: 'Chiquvchi', aiReplies: 'AI javoblari', humanReplies: 'Operator javoblari', messagesByDay: 'Kunlar bo‘yicha xabarlar',
    messagesByPlatform: 'Platformalar bo‘yicha xabarlar', inboundVsOutbound: 'Kiruvchi va chiquvchi', aiVsHuman: 'AI va operator javoblari',
    topCustomers: 'Eng faol mijozlar', noCustomers: 'Hali mijoz yo‘q', peakHours: 'Eng faol soatlar', mostProducts: 'Eng ko‘p tilga olingan mahsulotlar',
    productIntent: 'Katalog/mahsulot qiziqishi', priceQuestions: 'Narx so‘ragan mijozlar', priceHint: 'Narx savollari',
    deliveryQuestions: 'Yetkazib berishni so‘raganlar', deliveryHint: 'Yetkazib berish savollari', readyToOrder: 'Buyurtmaga tayyor mijozlar',
    buyingIntent: 'Sotib olish niyati', followUp: 'Operator kuzatuvi kerak', aiPaused: 'Takeover yoki AI pauzada',
    globalPrompt: 'Umumiy prompt', usedBy: 'Instagram + Telegram + WhatsApp uchun', platformOverrides: 'Platforma qoidalari',
    instagramRules: 'Instagram qoidalari', telegramRules: 'Telegram qoidalari', whatsappRules: 'WhatsApp qoidalari', businessKnowledge: 'Biznes bilimlari',
    knowledgeHint: 'Mahsulot, narx, yetkazib berish, FAQ, kontakt va katalog linklari Bilim sahifasida boshqariladi va promptga qo‘shiladi.',
    products: 'Mahsulotlar', prices: 'Narxlar', delivery: 'Yetkazib berish', faq: 'FAQ', contacts: 'Kontaktlar', catalogLinks: 'Katalog linklari',
    salesBehavior: 'Sotuv uslubi', openingMessage: 'Boshlang‘ich xabar', leadCollectionRules: 'Lead yig‘ish qoidalari',
    followUpStyle: 'Follow-up uslubi', humanHandoffRules: 'Operatorga o‘tkazish qoidalari', improvePrompt: 'Promptni yaxshilash', improving: 'Yaxshilanmoqda...',
    regenerate: 'Qayta yaratish', generatedSuggestion: 'Tavsiya qilingan prompt', suggestionFallback: 'Agentlarga osonroq, xavfsizroq va aniqroq qilindi.',
    acceptSuggestion: 'Tavsiyani qabul qilish', decline: 'Rad etish', savePromptSettings: 'AI prompt sozlamalarini saqlash', saving: 'Saqlanmoqda...',
    promptFormula: 'Prompt formulasi', noBusinesses: 'Backenddan bizneslar kelmadi.', connectInstagram: 'Instagram ulash', connectFacebook: 'Facebook ulash',
    unnamedBusiness: 'Nomsiz biznes', active: 'faol', paused: 'pauza', botEnabled: 'Bot yoqilgan', botEnabledHint: 'Bu biznes uchun avtomatik javoblarni boshqaradi.',
    instagramDms: 'Instagram DM', instagramDmsHint: 'Instagram DM avtomatik javoblari.', instagramComments: 'Instagram kommentlar',
    instagramCommentsHint: 'Kommentlarga avtomatik javoblar.', language: 'Til', tone: 'Ohang', aiModel: 'AI model', provider: 'Provider', model: 'Model',
    customModel: 'Custom model', temperature: 'Temperature', maxTokens: 'Max token', apiKeys: 'API kalitlar', key: 'kalit', saved: 'Saqlangan', pasteApiKey: 'API kalitni kiriting',
    clear: 'Tozalash', promptReady: 'Prompt tavsiyasi tayyor', promptLocal: 'Prompt tavsiyasi lokal yaratildi', noBusinessLocal: 'Live biznes tanlanmagani uchun lokal yaratildi.',
    backendUnavailableLocal: 'Backend endpoint hali ishlamagani uchun lokal yaratildi.',
    leadNew: 'Yangi', leadQualified: 'Saralangan', leadNegotiation: 'Muzokara', leadWon: 'Yutilgan', leadLost: 'Yo‘qotilgan',
    leadAmount: 'Potensial qiymat', leadSource: 'Manba', leadUpdated: 'Yangilangan', leadEmpty: 'Bu bosqichda lid yo‘q.',
    leadOpen: 'Chatni ochish', leadPrice: 'Narx', leadPricePlaceholder: 'Narx kiriting', leadPriceClear: 'Narxni o‘chirish',
    clientsTitle: 'Mijozlar jadvali', clientsSubtitle: 'Barcha mijozlar: status, kanal, narx va oxirgi xabar.', clientsEmpty: 'Hali mijoz yo‘q.',
    client: 'Mijoz', lastMessage: 'Oxirgi xabar', status: 'Status', channel: 'Kanal',
    operatorsTitle: 'Operator paneli', operatorsSubtitle: 'Vazifalar, mijoz xabarlari va lidlar uchun operator ish maydoni.',
    textToOperators: 'Operatorlarga topshiriq', textToOperatorsPlaceholder: 'Operatorlar uchun vazifa yozing...', saveAdminNote: 'Vazifani yuborish',
    adminNotes: 'Vazifalar tarixi', noAdminNotes: 'Hali vazifa yo‘q.', messagesFromClients: 'Mijozlardan xabarlar',
    tasksFromAdmin: 'Admindan vazifalar', noTasksForYou: 'Sizga tayinlangan vazifa yo‘q.',
    assignOne: 'Bitta operator', assignGroup: 'Guruhga', assignAll: 'Barcha operatorlar',
    operatorRanking: 'Operatorlar reytingi', successfulDeals: 'Muvaffaqiyatli bitimlar', operatorPanel: 'Operator panel', adminPanel: 'Admin panel',
    operatorAccounts: 'Operator akkauntlari', operatorAccountsHint: 'Bu biznes uchun operator loginlarini yarating.', operatorId: 'Operator ID', operatorPassword: 'Parol',
    addOperator: 'Operator qo‘shish', noOperators: 'Hali operator yo‘q.',
  },
  ru: {
    workspace: 'Рабочая область', leadsTitle: 'Воронка лидов', promptsTitle: 'Настройки AI Prompt', profile: 'Профиль', refresh: 'Обновить', liveWorkspace: 'Рабочая область backend',
    totalConversations: 'Всего диалогов', activeThreads: 'Активные диалоги inbox', newLeads: 'Новые лиды', recentProspects: 'Новые или непрочитанные клиенты',
    aiHandledChats: 'Чаты обработаны ИИ', coveredByAi: 'Сейчас ведет ИИ', humanTakeoverChats: 'Передано оператору', manualAttention: 'Нужно внимание человека',
    unreadMessages: 'Непрочитанные', waitingMessages: 'Сообщения ждут ответа', responseRate: 'Доля ответов', estimatedInbox: 'Оценка по inbox',
    avgResponseTime: 'Среднее время ответа', liveEstimate: 'Живая оценка', platformMessages: 'Сообщения платформ', allPlatforms: 'Instagram + Telegram + WhatsApp',
    inbound: 'Входящие', outbound: 'Исходящие', aiReplies: 'Ответы ИИ', humanReplies: 'Ответы оператора', messagesByDay: 'Сообщения по дням',
    messagesByPlatform: 'Сообщения по платформам', inboundVsOutbound: 'Входящие и исходящие', aiVsHuman: 'ИИ и оператор',
    topCustomers: 'Самые активные клиенты', noCustomers: 'Клиентов пока нет', peakHours: 'Пиковые часы', mostProducts: 'Часто упоминаемые товары',
    productIntent: 'Интерес к каталогу/товару', priceQuestions: 'Спрашивают цену', priceHint: 'Вопросы о цене',
    deliveryQuestions: 'Спрашивают доставку', deliveryHint: 'Вопросы о доставке', readyToOrder: 'Готовы заказать',
    buyingIntent: 'Намерение купить', followUp: 'Нужен follow-up оператора', aiPaused: 'Takeover или ИИ на паузе',
    globalPrompt: 'Общий prompt', usedBy: 'Для Instagram + Telegram + WhatsApp', platformOverrides: 'Правила платформ',
    instagramRules: 'Правила Instagram', telegramRules: 'Правила Telegram', whatsappRules: 'Правила WhatsApp', businessKnowledge: 'База знаний',
    knowledgeHint: 'Товары, цены, доставка, FAQ, контакты и ссылки каталога управляются на странице База знаний и добавляются в финальный prompt.',
    products: 'Товары', prices: 'Цены', delivery: 'Доставка', faq: 'FAQ', contacts: 'Контакты', catalogLinks: 'Ссылки каталога',
    salesBehavior: 'Стиль продаж', openingMessage: 'Первое сообщение', leadCollectionRules: 'Правила сбора лидов',
    followUpStyle: 'Стиль follow-up', humanHandoffRules: 'Правила передачи оператору', improvePrompt: 'Улучшить prompt', improving: 'Улучшаю...',
    regenerate: 'Сгенерировать заново', generatedSuggestion: 'Предложенный prompt', suggestionFallback: 'Сделано понятнее, безопаснее и проще для агентов.',
    acceptSuggestion: 'Принять', decline: 'Отклонить', savePromptSettings: 'Сохранить AI prompt', saving: 'Сохранение...',
    promptFormula: 'Формула prompt', noBusinesses: 'Backend не вернул бизнесы.', connectInstagram: 'Подключить Instagram', connectFacebook: 'Подключить Facebook',
    unnamedBusiness: 'Без названия', active: 'активен', paused: 'пауза', botEnabled: 'Бот включен', botEnabledHint: 'Управляет автоответами для бизнеса.',
    instagramDms: 'Instagram DM', instagramDmsHint: 'Автоответы в Instagram DM.', instagramComments: 'Комментарии Instagram',
    instagramCommentsHint: 'Автоответы на комментарии.', language: 'Язык', tone: 'Тон', aiModel: 'AI модель', provider: 'Провайдер', model: 'Модель',
    customModel: 'Своя модель', temperature: 'Temperature', maxTokens: 'Макс. токены', apiKeys: 'API ключи', key: 'ключ', saved: 'Сохранен', pasteApiKey: 'Вставьте API ключ',
    clear: 'Очистить', promptReady: 'Prompt готов', promptLocal: 'Prompt сгенерирован локально', noBusinessLocal: 'Создано локально, потому что live бизнес не выбран.',
    backendUnavailableLocal: 'Создано локально, потому что backend endpoint пока недоступен.',
    leadNew: 'Новые', leadQualified: 'Квалиф.', leadNegotiation: 'Переговоры', leadWon: 'Сделка', leadLost: 'Потеряно',
    leadAmount: 'Потенциал', leadSource: 'Источник', leadUpdated: 'Обновлено', leadEmpty: 'В этой стадии пока нет лидов.',
    leadOpen: 'Открыть чат', leadPrice: 'Цена', leadPricePlaceholder: 'Добавить цену', leadPriceClear: 'Удалить цену',
    clientsTitle: 'Таблица клиентов', clientsSubtitle: 'Все клиенты со статусом, каналом, ценой и последним сообщением.', clientsEmpty: 'Клиентов пока нет.',
    client: 'Клиент', lastMessage: 'Последнее сообщение', status: 'Статус', channel: 'Канал',
    operatorsTitle: 'Панель оператора', operatorsSubtitle: 'Рабочая зона оператора: задачи, клиенты и лиды.',
    textToOperators: 'Задача операторам', textToOperatorsPlaceholder: 'Напишите задачу для операторов...', saveAdminNote: 'Отправить задачу',
    adminNotes: 'История задач', noAdminNotes: 'Задач пока нет.', messagesFromClients: 'Сообщения клиентов',
    tasksFromAdmin: 'Задачи от админа', noTasksForYou: 'Вам пока не назначены задачи.',
    assignOne: 'Одному', assignGroup: 'Группе', assignAll: 'Всем операторам',
    operatorRanking: 'Рейтинг операторов', successfulDeals: 'Успешные сделки', operatorPanel: 'Панель оператора', adminPanel: 'Панель админа',
    operatorAccounts: 'Аккаунты операторов', operatorAccountsHint: 'Создайте логины операторов для этого бизнеса.', operatorId: 'ID оператора', operatorPassword: 'Пароль',
    addOperator: 'Добавить оператора', noOperators: 'Операторов пока нет.',
  },
};

const LEAD_STAGE_ORDER = ['new', 'qualified', 'negotiation', 'won', 'lost'];

function guessLeadStage(conv) {
  const blob = `${conv.preview} ${conv.summary}`.toLowerCase();
  if (conv.unread > 0 || conv.needsHuman) return 'new';
  if (/ready|order|заказ|buyurtma|olaman|сч[её]т|invoice/.test(blob)) return 'negotiation';
  if (/thank|thanks|received|получил|rahmat|oldim/.test(blob)) return 'won';
  if (/cancel|later|нет|yo['’`]?q|not now|stop/.test(blob)) return 'lost';
  return 'qualified';
}

function buildLeads(conversations, leadStages, leadPrices = {}) {
  const leads = (conversations || []).map(conv => {
    const stage = leadStages[conv.id] || guessLeadStage(conv);
    const inferredValue = Number(conv.kpis?.orders || 0) > 0
      ? Number(conv.kpis.orders) * 120
      : Math.max(90, 60 + Number(conv.unread || 0) * 45 + (conv.needsHuman ? 120 : 0));
    return {
      id: conv.id,
      stage,
      name: conv.name,
      platform: conv.platform,
      handle: conv.handle,
      preview: conv.preview,
      unread: conv.unread,
      needsHuman: conv.needsHuman,
      amount: inferredValue,
      price: leadPrices[conv.id] || '',
      updatedAt: conv.lastTime,
      source: conv.channelName || conv.channel || conv.platform,
      conversationId: conv.id,
    };
  });
  return leads;
}

function localPromptSuggestion(field, currentPrompt = '', goal = '') {
  const intro = {
    global_prompt: 'You are a natural sales assistant for this business across Instagram, Telegram, and WhatsApp.',
    instagram_prompt: 'Instagram DM rules:',
    telegram_prompt: 'Telegram rules:',
    whatsapp_prompt: 'WhatsApp rules:',
    opening_message: 'Assalomu alaykum 😊 Qanday yordam kerak?',
    lead_collection_rules: 'Lead collection rules:',
    sales_rules: 'Sales reply rules:',
    handoff_rules: 'Human handoff rules:',
  }[field] || 'Prompt rules:';

  const source = String(currentPrompt || '').trim();
  const productHint = source.match(/[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳʼ']{4,}/)?.[0] || 'customer request';

  if (field === 'opening_message') {
    return {
      suggested_prompt: 'Assalomu alaykum 😊 Qanday yordam kerak?',
      explanation: 'Made the opening short and natural, without asking for phone or address too early.',
    };
  }

  return {
    suggested_prompt: [
      intro,
      `- Reply shortly, warmly, and naturally in the customer's language.`,
      `- First answer the customer's question, then ask only one simple follow-up question.`,
      `- Do not ask for phone number or address at the beginning.`,
      `- Ask for phone/address only when the customer is clearly ready to order.`,
      `- Do not repeat "${productHint}" or any product name in every message.`,
      `- Never invent price, stock, delivery time, discounts, or availability.`,
      `- Avoid corporate phrases like "manager will contact you" unless the customer asks for a human or is ready to order.`,
      `- If the customer is annoyed, reply calmly and briefly before continuing.`,
      goal ? `- Main improvement goal: ${goal}.` : '',
    ].filter(Boolean).join('\n'),
    explanation: 'Made it shorter, clearer, safer for sales replies, and aligned with Instaagent standards.',
  };
}

function clampPercent(value, max) {
  if (!max) return 0;
  return Math.max(4, Math.min(100, Math.round((Number(value || 0) / max) * 100)));
}

function formatPercent(value) {
  if (!Number.isFinite(value)) return '0%';
  return `${Math.round(value)}%`;
}

function keywordCount(conversations, words) {
  const terms = words.map(word => word.toLowerCase());
  return conversations.filter(conv => terms.some(term => `${conv.name} ${conv.preview} ${conv.summary}`.toLowerCase().includes(term))).length;
}

function buildInsights(conversations, stats, w = WORKSPACE_TEXT.en) {
  const rows = conversations || [];
  const totalConversations = rows.length;
  const unreadMessages = rows.reduce((sum, conv) => sum + Number(conv.unread || 0), 0);
  const aiHandled = rows.filter(conv => conv.aiOn && !conv.needsHuman).length;
  const humanTakeover = rows.filter(conv => conv.needsHuman || conv.aiOn === false).length;
  const newLeads = rows.filter(conv => conv.unread > 0 || /first|today|2 min|14 min|hr/i.test(`${conv.customerSince} ${conv.lastTime}`)).length;
  const responseRate = totalConversations ? ((totalConversations - unreadMessages) / totalConversations) * 100 : 0;

  const platformCounts = ['instagram', 'telegram', 'whatsapp'].map(platform => ({
    label: platform === 'whatsapp' ? 'WhatsApp' : platform[0].toUpperCase() + platform.slice(1),
    value: rows.filter(conv => conv.platform === platform).length || Number(stats?.[`${platform}_messages`] || 0),
  }));

  const inboundOutbound = [
    { label: w.inbound, value: rows.reduce((sum, conv) => sum + Number(conv.unread || 0), 0) + totalConversations },
    { label: w.outbound, value: rows.filter(conv => conv.aiOn).length + rows.filter(conv => conv.lastFromMe).length },
  ];

  const aiHuman = [
    { label: w.aiReplies, value: aiHandled },
    { label: w.humanReplies, value: humanTakeover },
  ];

  const dayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const messagesByDay = dayLabels.map((label, index) => ({
    label,
    value: Math.max(1, Math.round((totalConversations + unreadMessages + index * 2) * (0.55 + ((index % 3) * 0.18)))),
  }));

  const peakHours = ['09', '11', '13', '15', '17', '19'].map((label, index) => ({
    label: `${label}:00`,
    value: Math.max(1, Math.round((totalConversations + 2) * (0.45 + ((index + 1) % 4) * 0.16))),
  }));

  const topCustomers = rows
    .slice()
    .sort((a, b) => (Number(b.kpis?.orders || 0) + Number(b.unread || 0)) - (Number(a.kpis?.orders || 0) + Number(a.unread || 0)))
    .slice(0, 5)
    .map(conv => ({ label: conv.name, value: Number(conv.kpis?.orders || 0) || Number(conv.unread || 0) || 1, platform: conv.platform }));

  const productTerms = ['xalat', 'sumka', 'dress', 'shoe', 'catalog', 'katalog', 'mahsulot', 'товар', 'collection'];
  const priceTerms = ['price', 'narx', 'qancha', 'сколько', 'цена'];
  const deliveryTerms = ['delivery', 'yetkaz', 'dostavka', 'доставка'];
  const orderTerms = ['order', 'buyurtma', 'olaman', 'куплю', 'zakaz', 'ready'];

  return {
    metrics: [
      { label: w.totalConversations, value: totalConversations, hint: w.activeThreads },
      { label: w.newLeads, value: newLeads, hint: w.recentProspects },
      { label: w.aiHandledChats, value: aiHandled, hint: w.coveredByAi },
      { label: w.humanTakeoverChats, value: humanTakeover, hint: w.manualAttention },
      { label: w.unreadMessages, value: unreadMessages, hint: w.waitingMessages },
      { label: w.responseRate, value: formatPercent(responseRate), hint: w.estimatedInbox },
      { label: w.avgResponseTime, value: unreadMessages ? '14m' : '6m', hint: w.liveEstimate },
      { label: w.platformMessages, value: platformCounts.reduce((sum, item) => sum + item.value, 0), hint: w.allPlatforms },
    ],
    platformCounts,
    inboundOutbound,
    aiHuman,
    messagesByDay,
    topCustomers,
    peakHours,
    salesSignals: [
      { label: w.mostProducts, value: keywordCount(rows, productTerms), hint: w.productIntent },
      { label: w.priceQuestions, value: keywordCount(rows, priceTerms), hint: w.priceHint },
      { label: w.deliveryQuestions, value: keywordCount(rows, deliveryTerms), hint: w.deliveryHint },
      { label: w.readyToOrder, value: keywordCount(rows, orderTerms), hint: w.buyingIntent },
      { label: w.followUp, value: humanTakeover, hint: w.aiPaused },
    ],
  };
}

function MiniBarChart({ title, data }) {
  const max = Math.max(1, ...data.map(item => Number(item.value || 0)));
  return (
    <div className="chart-card">
      <h3>{title}</h3>
      <div className="bar-chart">
        {data.map(item => (
          <div className="bar-row" key={item.label}>
            <span>{item.label}</span>
            <div className="bar-track"><i style={{ width: `${clampPercent(item.value, max)}%` }} /></div>
            <b>{item.value}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

function ColumnChart({ title, data }) {
  const max = Math.max(1, ...data.map(item => Number(item.value || 0)));
  return (
    <div className="chart-card">
      <h3>{title}</h3>
      <div className="column-chart">
        {data.map(item => (
          <div className="column" key={item.label}>
            <i style={{ height: `${clampPercent(item.value, max)}%` }} />
            <span>{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function InsightsDashboard({ conversations, stats, w }) {
  const insights = buildInsights(conversations, stats, w);
  return (
    <div className="insights-dashboard">
      <div className="insights-metrics">
        {insights.metrics.map(metric => (
          <div className="metric-card rich" key={metric.label}>
            <span>{metric.label}</span>
            <b>{metric.value}</b>
            <em>{metric.hint}</em>
          </div>
        ))}
      </div>

      <div className="charts-grid">
        <ColumnChart title={w.messagesByDay} data={insights.messagesByDay} />
        <MiniBarChart title={w.messagesByPlatform} data={insights.platformCounts} />
        <MiniBarChart title={w.inboundVsOutbound} data={insights.inboundOutbound} />
        <MiniBarChart title={w.aiVsHuman} data={insights.aiHuman} />
        <MiniBarChart title={w.topCustomers} data={insights.topCustomers.length ? insights.topCustomers : [{ label: w.noCustomers, value: 0 }]} />
        <ColumnChart title={w.peakHours} data={insights.peakHours} />
      </div>

      <div className="sales-insights">
        {insights.salesSignals.map(signal => (
          <div className="signal-card" key={signal.label}>
            <span>{signal.label}</span>
            <b>{signal.value}</b>
            <em>{signal.hint}</em>
          </div>
        ))}
      </div>
    </div>
  );
}

function PromptGeneratorField({
  field,
  label,
  value,
  rows = 5,
  businessId,
  onChange,
  onGeneratePrompt,
  generatorState,
  w = WORKSPACE_TEXT.en,
}) {
  const state = generatorState[field] || {};
  const hasSuggestion = !!state.suggestedPrompt;
  const improve = () => onGeneratePrompt(field, value, 'make it more natural and sales-focused');

  return (
    <div className="prompt-generator-field">
      <PromptField label={label} value={value} rows={rows} onChange={onChange} />
      <div className="prompt-tools">
        <button className="panel-btn subtle" disabled={state.loading} onClick={improve}>
          {state.loading ? w.improving : w.improvePrompt}
        </button>
        {hasSuggestion && (
          <button className="panel-btn subtle" disabled={state.loading} onClick={() => onGeneratePrompt(field, value, 'regenerate with a clearer and more practical sales style')}>
            {w.regenerate}
          </button>
        )}
      </div>
      {hasSuggestion && (
        <div className="suggestion-card">
          <div>
            <span>{w.generatedSuggestion}</span>
            <p>{state.explanation || w.suggestionFallback}</p>
          </div>
          <pre>{state.suggestedPrompt}</pre>
          <div className="panel-actions">
            <button onClick={() => { onChange(state.suggestedPrompt); onGeneratePrompt(field, state.suggestedPrompt, 'decline'); }}>{w.acceptSuggestion}</button>
            <button className="subtle-action" onClick={() => onGeneratePrompt(field, value, 'decline')}>{w.decline}</button>
          </div>
        </div>
      )}
    </div>
  );
}

function LeadsBoard({ conversations, leadStages, leadPrices, setLeadStage, setLeadPrice, onOpenConversation, w }) {
  const leads = useMemo(() => buildLeads(conversations, leadStages, leadPrices), [conversations, leadStages, leadPrices]);
  const stageNames = {
    new: w.leadNew,
    qualified: w.leadQualified,
    negotiation: w.leadNegotiation,
    won: w.leadWon,
    lost: w.leadLost,
  };
  return (
    <div className="leads-board">
      {LEAD_STAGE_ORDER.map(stage => {
        const list = leads.filter(item => item.stage === stage);
        return (
          <section className={`lead-column lead-stage-${stage}`} key={stage}>
            <header>
              <h3>{stageNames[stage]}</h3>
              <span>{list.length}</span>
            </header>
            <div className="lead-list">
              {!list.length && <div className="lead-empty">{w.leadEmpty}</div>}
              {list.map(lead => (
                <article className="lead-card" key={lead.id}>
                  <div className="lead-head">
                    <strong>{lead.name}</strong>
                    <span>{lead.platform}</span>
                  </div>
                  <p>{lead.preview}</p>
                  <div className="lead-meta">
                    <span>{w.leadSource}: <b>{lead.source}</b></span>
                    <span>{w.leadUpdated}: <b>{lead.updatedAt}</b></span>
                  </div>
                  <label className="lead-price-row">
                    <span>{w.leadPrice}</span>
                    <input
                      value={lead.price}
                      placeholder={w.leadPricePlaceholder}
                      onChange={(e) => setLeadPrice(lead.id, e.target.value)}
                    />
                    {lead.price && (
                      <button type="button" title={w.leadPriceClear} onClick={() => setLeadPrice(lead.id, '')}>x</button>
                    )}
                  </label>
                  <div className="lead-actions">
                    <select value={lead.stage} onChange={(e) => setLeadStage(lead.id, e.target.value)}>
                      {LEAD_STAGE_ORDER.map(option => (
                        <option key={option} value={option}>{stageNames[option]}</option>
                      ))}
                    </select>
                    <button onClick={() => onOpenConversation(lead.conversationId)}>{w.leadOpen}</button>
                  </div>
                </article>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function ClientsTable({ conversations, leadStages, leadPrices, onOpenConversation, w }) {
  const rows = useMemo(() => (conversations || []).map(conv => ({
    ...conv,
    stage: leadStages[conv.id] || guessLeadStage(conv),
    price: leadPrices[conv.id] || '',
  })), [conversations, leadStages, leadPrices]);

  const stageNames = {
    new: w.leadNew,
    qualified: w.leadQualified,
    negotiation: w.leadNegotiation,
    won: w.leadWon,
    lost: w.leadLost,
  };

  return (
    <div className="clients-section">
      <div className="section-card-head">
        <div>
          <h3>{w.clientsTitle}</h3>
          <p>{w.clientsSubtitle}</p>
        </div>
        <span>{rows.length}</span>
      </div>
      <div className="clients-table-wrap">
        <table className="clients-table">
          <thead>
            <tr>
              <th>{w.client}</th>
              <th>{w.channel}</th>
              <th>{w.status}</th>
              <th>{w.leadPrice}</th>
              <th>{w.lastMessage}</th>
              <th>{w.unreadMessages}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {!rows.length && (
              <tr>
                <td colSpan="7" className="clients-empty">{w.clientsEmpty}</td>
              </tr>
            )}
            {rows.map(row => (
              <tr key={row.id}>
                <td>
                  <div className="client-cell">
                    <Avatar data={row.avatar} size={32} platform={row.platform} />
                    <span>
                      <strong>{row.name}</strong>
                      <em>{row.handle}</em>
                    </span>
                  </div>
                </td>
                <td>{row.channelName || row.platform}</td>
                <td><span className={`stage-pill stage-${row.stage}`}>{stageNames[row.stage]}</span></td>
                <td>{row.price || '-'}</td>
                <td className="client-preview">{row.preview}</td>
                <td>{row.unread || 0}</td>
                <td><button className="table-action" onClick={() => onOpenConversation(row.id)}>{w.leadOpen}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OperatorsRanking({ leadStages, operatorDeals = {}, operatorAccounts = [], setOperatorDealCount, w }) {
  const wonDeals = Object.values(leadStages || {}).filter(stage => stage === 'won').length;
  const accountRows = Array.isArray(operatorAccounts)
    ? operatorAccounts
      .filter(item => String(item?.role || '').toLowerCase() === 'operator')
      .map(item => {
        const loginId = String(item?.login_id || '').trim();
        if (!loginId) return null;
        const dealValue = Number(operatorDeals[loginId] ?? operatorDeals[loginId.toLowerCase()] ?? 0);
        const displayName = loginId.charAt(0).toUpperCase() + loginId.slice(1);
        return {
          id: loginId,
          name: displayName,
          deals: Number.isFinite(dealValue) ? dealValue : 0,
        };
      })
      .filter(Boolean)
    : [];

  const rows = accountRows.length
    ? accountRows.sort((a, b) => b.deals - a.deals)
    : [{ id: 'unassigned', name: 'Unassigned', deals: Number(operatorDeals.unassigned ?? wonDeals ?? 0) }];

  return (
    <section className="operator-ranking">
      <div className="section-card-head">
        <div>
          <h3>{w.operatorRanking}</h3>
          <p>{w.successfulDeals}</p>
        </div>
      </div>
      <div className="operator-rank-list">
        {rows.map((row, index) => (
          <label className="operator-rank-row" key={row.id}>
            <span className="rank-number">{index + 1}</span>
            <strong>{row.name}</strong>
            <input
              type="number"
              min="0"
              value={row.deals}
              onChange={(e) => setOperatorDealCount(row.id, e.target.value)}
            />
          </label>
        ))}
      </div>
    </section>
  );
}

function OperatorAccountsPanel({ selectedBusinessId, onToast, w, readOnly = false, compactTitle = false, operatorsData = null, onReload = null }) {
  const [operators, setOperators] = useState([]);
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const [saving, setSaving] = useState(false);

  const loadOperators = async () => {
    if (operatorsData) return;
    try {
      const fallback = await API.get('/api/v2/operators');
      setOperators(fallback.data || []);
    } catch (e) {
      // Keep previous list when a transient request fails.
    }
  };

  useEffect(() => {
    if (!operatorsData) loadOperators();
  }, [selectedBusinessId, operatorsData]);

  useEffect(() => {
    if (onReload) onReload();
  }, [onReload, selectedBusinessId]);

  const createOperator = async (e) => {
    e.preventDefault();
    if (readOnly) return;
    if (!selectedBusinessId || !loginId.trim() || !password.trim()) return;
    setSaving(true);
    try {
      await API.postJson('/api/v2/operators', {
        business_id: selectedBusinessId,
        login_id: loginId.trim(),
        password,
      });
      setLoginId('');
      setPassword('');
      onToast('Operator account created');
      if (onReload) onReload();
      else loadOperators();
    } catch (err) {
      onToast(err.message || 'Could not create operator');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="operator-accounts-card">
      <div className="section-card-head">
        <div>
          <h3>{compactTitle ? (w.operatorsTitle || 'Operators') : w.operatorAccounts}</h3>
          <p>{compactTitle ? w.messagesFromClients : w.operatorAccountsHint}</p>
        </div>
        <span>{(operatorsData || operators).length}</span>
      </div>
      {!readOnly && (
        <form className="operator-account-form" onSubmit={createOperator}>
          <label className="field-row">
            <span>{w.operatorId}</span>
            <input value={loginId} onChange={(e) => setLoginId(e.target.value)} placeholder="operator@business.com" />
          </label>
          <label className="field-row">
            <span>{w.operatorPassword}</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Minimum 6 characters" />
          </label>
          <button disabled={saving || !loginId.trim() || password.length < 6}>{saving ? w.saving : w.addOperator}</button>
        </form>
      )}
      <div className="operator-account-list">
        {!(operatorsData || operators).length && <span>{w.noOperators}</span>}
        {(operatorsData || operators).map(operator => (
          <div key={operator.login_id}>
            <strong>{operator.login_id}</strong>
            <em>{operator.role || 'operator'}</em>
          </div>
        ))}
      </div>
    </section>
  );
}

function BusinessChannelsManager({ selectedBusiness, onToast }) {
  const businessId = String(selectedBusiness?.id || '').trim();
  const [channels, setChannels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    platform: 'instagram',
    accountLabel: '',
    externalAccountId: '',
    accessToken: '',
    pageAccessToken: '',
    phoneNumberId: '',
    wabaId: '',
    botToken: '',
  });

  const loadChannels = async () => {
    if (!businessId) {
      setChannels([]);
      return;
    }
    setLoading(true);
    try {
      const data = await API.get(`/api/businesses/${encodeURIComponent(businessId)}/channels`);
      setChannels(data.data || []);
    } catch (e) {
      setChannels([]);
      onToast(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadChannels();
  }, [businessId]);

  const onChange = (key, value) => setForm(prev => ({ ...prev, [key]: value }));

  const addChannel = async (e) => {
    e.preventDefault();
    if (!businessId) return;
    const platform = String(form.platform || '').trim().toLowerCase();
    const accountLabel = String(form.accountLabel || '').trim();
    const externalAccountId = String(form.externalAccountId || '').trim();
    if (!platform || !accountLabel || !externalAccountId) {
      onToast('Platform, account name, and external account ID are required.');
      return;
    }

    const config = {};
    if (form.accessToken.trim()) config.access_token = form.accessToken.trim();
    if (form.pageAccessToken.trim()) config.page_access_token = form.pageAccessToken.trim();
    if (form.phoneNumberId.trim()) config.phone_number_id = form.phoneNumberId.trim();
    if (form.wabaId.trim()) config.waba_id = form.wabaId.trim();
    if (form.botToken.trim()) config.bot_token = form.botToken.trim();

    setSaving(true);
    try {
      await API.postJson(`/api/businesses/${encodeURIComponent(businessId)}/channels`, {
        platform,
        account_label: accountLabel,
        account_external_id: externalAccountId,
        is_active: true,
        config,
      });
      onToast('Channel saved');
      setForm(prev => ({
        ...prev,
        accountLabel: '',
        externalAccountId: '',
        accessToken: '',
        pageAccessToken: '',
        phoneNumberId: '',
        wabaId: '',
        botToken: '',
      }));
      await loadChannels();
    } catch (e2) {
      onToast(e2.message);
    } finally {
      setSaving(false);
    }
  };

  const removeChannel = async (channelId) => {
    if (!channelId) return;
    try {
      await API.delete(`/api/business-channels/${encodeURIComponent(channelId)}`);
      onToast('Channel removed');
      await loadChannels();
    } catch (e) {
      onToast(e.message);
    }
  };

  return (
    <div className="channel-manager">
      <div className="settings-section">
        <h3>Connected channels</h3>
        <p className="section-hint">Add multiple Instagram/WhatsApp/Telegram accounts for this business.</p>
        {loading ? <div className="empty">Loading... please wait</div> : (
          <div className="channel-list">
            {(channels || []).map(row => (
              <div className="channel-row" key={row.id}>
                <span>
                  <strong>{row.account_label || row.platform}</strong>
                  <em>{row.platform} · {row.account_external_id}</em>
                </span>
                <button className="ghost" onClick={() => removeChannel(row.id)}>Remove</button>
              </div>
            ))}
            {!channels.length && <div className="empty">No channels connected yet.</div>}
          </div>
        )}
      </div>

      <form className="settings-section" onSubmit={addChannel}>
        <h3>Add channel</h3>
        <div className="model-grid">
          <label className="field-row">
            <span>Platform</span>
            <select value={form.platform} onChange={(e) => onChange('platform', e.target.value)}>
              <option value="instagram">Instagram</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="telegram">Telegram</option>
              <option value="telegram_bot">Telegram Bot</option>
            </select>
          </label>
          <label className="field-row">
            <span>Account name</span>
            <input value={form.accountLabel} onChange={(e) => onChange('accountLabel', e.target.value)} placeholder="Milana Premium IG 2" />
          </label>
        </div>
        <label className="field-row">
          <span>External account ID</span>
          <input value={form.externalAccountId} onChange={(e) => onChange('externalAccountId', e.target.value)} placeholder="IG business ID / WhatsApp phone_number_id / Bot username" />
        </label>
        <div className="model-grid">
          <label className="field-row">
            <span>Access token</span>
            <input value={form.accessToken} onChange={(e) => onChange('accessToken', e.target.value)} placeholder="Optional token" />
          </label>
          <label className="field-row">
            <span>Page access token</span>
            <input value={form.pageAccessToken} onChange={(e) => onChange('pageAccessToken', e.target.value)} placeholder="Instagram/Facebook page token" />
          </label>
        </div>
        <div className="model-grid">
          <label className="field-row">
            <span>WhatsApp phone_number_id</span>
            <input value={form.phoneNumberId} onChange={(e) => onChange('phoneNumberId', e.target.value)} placeholder="Optional" />
          </label>
          <label className="field-row">
            <span>WhatsApp WABA ID</span>
            <input value={form.wabaId} onChange={(e) => onChange('wabaId', e.target.value)} placeholder="Optional" />
          </label>
        </div>
        <label className="field-row">
          <span>Telegram bot token</span>
          <input value={form.botToken} onChange={(e) => onChange('botToken', e.target.value)} placeholder="Optional" />
        </label>
        <div className="panel-actions">
          <button type="submit" disabled={saving || !businessId}>{saving ? 'Saving...' : 'Save channel'}</button>
        </div>
      </form>
    </div>
  );
}

function AdminTaskDispatchCard({ adminNotes, onAdminNote, operatorAccounts = [], w }) {
  const [draft, setDraft] = useState('');
  const [assignMode, setAssignMode] = useState('one');
  const operatorIds = useMemo(
    () => (operatorAccounts || [])
      .filter(item => String(item?.role || '').toLowerCase() === 'operator')
      .map(item => String(item?.login_id || '').trim())
      .filter(Boolean),
    [operatorAccounts],
  );
  const [singleOperator, setSingleOperator] = useState('');
  const [groupOperators, setGroupOperators] = useState([]);

  useEffect(() => {
    if (!singleOperator && operatorIds.length) setSingleOperator(operatorIds[0]);
  }, [operatorIds, singleOperator]);

  const toggleGroupOperator = (operatorId) => {
    setGroupOperators(prev => prev.includes(operatorId) ? prev.filter(item => item !== operatorId) : [...prev, operatorId]);
  };

  const saveTask = () => {
    const clean = draft.trim();
    if (!clean) return;
    let recipients = [];
    if (assignMode === 'all') recipients = ['*'];
    else if (assignMode === 'group') recipients = groupOperators;
    else recipients = singleOperator ? [singleOperator] : [];
    if (!recipients.length) return;
    onAdminNote(clean, recipients, assignMode);
    setDraft('');
  };

  return (
    <section className="operator-note-card">
      <div className="section-card-head">
        <div>
          <h3>{w.textToOperators}</h3>
          <p>{w.operatorsSubtitle}</p>
        </div>
      </div>
      <div className="operators-mode-switch" style={{ marginBottom: 10 }}>
        <button type="button" className={assignMode === 'one' ? 'active' : ''} onClick={() => setAssignMode('one')}>{w.assignOne}</button>
        <button type="button" className={assignMode === 'group' ? 'active' : ''} onClick={() => setAssignMode('group')}>{w.assignGroup}</button>
        <button type="button" className={assignMode === 'all' ? 'active' : ''} onClick={() => setAssignMode('all')}>{w.assignAll}</button>
      </div>
      {assignMode === 'one' && (
        <label className="field-row">
          <span>{w.assignOne}</span>
          <select value={singleOperator} onChange={(e) => setSingleOperator(e.target.value)}>
            {operatorIds.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
      )}
      {assignMode === 'group' && (
        <div className="operator-account-list" style={{ marginBottom: 10 }}>
          {operatorIds.map(item => (
            <label key={item} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input type="checkbox" checked={groupOperators.includes(item)} onChange={() => toggleGroupOperator(item)} />
              <strong>{item}</strong>
            </label>
          ))}
        </div>
      )}
      <textarea value={draft} placeholder={w.textToOperatorsPlaceholder} onChange={(e) => setDraft(e.target.value)} rows={5} />
      <div className="panel-actions">
        <button disabled={!draft.trim()} onClick={saveTask}>{w.saveAdminNote}</button>
      </div>
      <div className="admin-note-list">
        <strong>{w.adminNotes}</strong>
        {!adminNotes.length && <span>{w.noAdminNotes}</span>}
        {adminNotes.slice(0, 6).map(note => (
          <p key={note.id}>
            {note.text}
            {Array.isArray(note.recipients) && note.recipients.length
              ? ` (${note.recipients[0] === '*' ? w.assignAll : note.recipients.join(', ')})`
              : ''}
          </p>
        ))}
      </div>
    </section>
  );
}

function OperatorTaskInboxCard({ adminNotes = [], currentUser, w }) {
  const currentLogin = String(currentUser?.ownerEmail || currentUser?.email || '').trim().toLowerCase();
  const tasks = useMemo(
    () => (adminNotes || []).filter(note => {
      const recipients = Array.isArray(note?.recipients) ? note.recipients.map(item => String(item || '').trim().toLowerCase()) : ['*'];
      if (!recipients.length) return true;
      if (recipients.includes('*')) return true;
      return recipients.includes(currentLogin);
    }),
    [adminNotes, currentLogin],
  );

  return (
    <section className="operator-note-card">
      <div className="section-card-head">
        <div>
          <h3>{w.tasksFromAdmin}</h3>
          <p>{w.operatorsSubtitle}</p>
        </div>
      </div>
      <div className="admin-note-list">
        {!tasks.length && <span>{w.noTasksForYou}</span>}
        {tasks.slice(0, 8).map(task => (
          <p key={task.id}>{task.text}</p>
        ))}
      </div>
    </section>
  );
}

function OperatorMessagesCard({ conversations, onOpenConversation, w }) {
  const priorityRows = useMemo(() => [...(conversations || [])]
    .sort((a, b) => Number(b.unread || 0) - Number(a.unread || 0))
    .slice(0, 8), [conversations]);

  return (
    <section className="operator-messages-card">
      <div className="section-card-head">
        <div>
          <h3>{w.messagesFromClients}</h3>
          <p>{w.clientsSubtitle}</p>
        </div>
        <span>{priorityRows.length}</span>
      </div>
      <div className="operator-message-list">
        {priorityRows.map(row => (
          <button key={row.id} onClick={() => onOpenConversation(row.id)}>
            <Avatar data={row.avatar} size={32} platform={row.platform} />
            <span>
              <strong>{row.name}</strong>
              <em>{row.preview}</em>
            </span>
            <b>{row.unread || 0}</b>
          </button>
        ))}
      </div>
    </section>
  );
}

function AdminPanel(props) {
  const { conversations, leadStages, leadPrices, operatorDeals, adminNotes, onAdminNote, setOperatorDealCount, setLeadStage, setLeadPrice, onOpenConversation, selectedBusinessId, operatorAccounts, onReloadOperatorAccounts, w } = props;
  return (
    <div className="operator-panel">
      <AdminTaskDispatchCard adminNotes={adminNotes} onAdminNote={onAdminNote} operatorAccounts={operatorAccounts} w={w} />
      <OperatorMessagesCard conversations={conversations} onOpenConversation={onOpenConversation} w={w} />
      <OperatorAccountsPanel selectedBusinessId="" onToast={() => {}} w={w} readOnly operatorsData={operatorAccounts} onReload={onReloadOperatorAccounts} />
      <OperatorsRanking
        leadStages={leadStages}
        operatorDeals={operatorDeals}
        operatorAccounts={operatorAccounts}
        setOperatorDealCount={setOperatorDealCount}
        w={w}
      />
      <section className="operator-leads-card">
        <div className="section-card-head">
          <div>
            <h3>{w.leadsTitle}</h3>
            <p>{w.clientsSubtitle}</p>
          </div>
        </div>
        <LeadsBoard conversations={conversations} leadStages={leadStages} leadPrices={leadPrices} setLeadStage={setLeadStage} setLeadPrice={setLeadPrice} onOpenConversation={onOpenConversation} w={w} />
      </section>
    </div>
  );
}

function OperatorPanel(props) {
  const { conversations, leadStages, leadPrices, adminNotes, setLeadStage, setLeadPrice, onOpenConversation, w, currentUser } = props;
  return (
    <div className="operator-panel">
      <OperatorTaskInboxCard adminNotes={adminNotes} currentUser={currentUser} w={w} />
      <OperatorMessagesCard conversations={conversations} onOpenConversation={onOpenConversation} w={w} />
      <section className="operator-leads-card">
        <div className="section-card-head">
          <div>
            <h3>{w.leadsTitle}</h3>
            <p>{w.clientsSubtitle}</p>
          </div>
        </div>
        <LeadsBoard conversations={conversations} leadStages={leadStages} leadPrices={leadPrices} setLeadStage={setLeadStage} setLeadPrice={setLeadPrice} onOpenConversation={onOpenConversation} w={w} />
      </section>
    </div>
  );
}

function OperatorsSection(props) {
  const isOperator = props.currentUser?.role === 'operator' && props.currentUser?.isAdmin !== true;
  const [mode, setMode] = useState(isOperator ? 'operator' : 'admin');
  const w = props.w;
  if (isOperator) return <OperatorPanel {...props} />;
  return (
    <div className="operators-section">
      <div className="operators-mode-switch" role="tablist" aria-label={w.operatorsTitle}>
        <button className={mode === 'admin' ? 'active' : ''} onClick={() => setMode('admin')} role="tab" aria-selected={mode === 'admin'}>{w.adminPanel}</button>
        <button className={mode === 'operator' ? 'active' : ''} onClick={() => setMode('operator')} role="tab" aria-selected={mode === 'operator'}>{w.operatorPanel}</button>
      </div>
      {mode === 'admin' ? <AdminPanel {...props} /> : <OperatorPanel {...props} />}
    </div>
  );
}

function WorkspacePanel({
  lang,
  t,
  view,
  stats,
  conversations,
  businesses,
  selectedBusinessId,
  onSelectBusiness,
  onRefresh,
  onBusinessSetting,
  promptSettings,
  onPromptSetting,
  onSavePromptSettings,
  promptLoading,
  promptSaving,
  onToast,
  onGeneratePrompt,
  generatorState,
  leadStages,
  leadPrices,
  operatorDeals,
  adminNotes,
  operatorAccounts,
  onReloadOperatorAccounts,
  onLeadStageChange,
  onLeadPriceChange,
  onOperatorDealChange,
  onAdminNote,
  onOpenConversation,
  ownerEmail,
  onOwnerEmailSave,
  onSignOut,
  currentUser,
  userProfile,
  onUpdateUserProfile,
}) {
  const w = WORKSPACE_TEXT[lang] || WORKSPACE_TEXT.en;
  const isOperator = currentUser?.role === 'operator' && currentUser?.isAdmin !== true;
  if (isOperator && !['leads', 'inbox', 'operators', 'settings', 'profile'].includes(view)) return null;
  const selectedBusiness = businesses.find(b => b.id === selectedBusinessId) || businesses[0] || {};
  const activeProviderId = aiProviderForBusiness(selectedBusiness);
  const activeProvider = AI_PROVIDERS.find(provider => provider.id === activeProviderId) || AI_PROVIDERS[0];
  const activeModel = selectedBusiness.ai_model || activeProvider.defaultModel;
  const modelSelectValue = activeProvider.models.includes(activeModel) ? activeModel : 'custom';
  const title = {
    insights: t.insights,
    leads: t.leads,
    clients: t.clients || w.clientsTitle,
    operators: t.operators || w.operatorsTitle,
    knowledge: t.knowledge,
    prompts: w.promptsTitle,
    accounts: t.accounts,
    settings: t.settings,
    profile: w.profile,
  }[view] || w.workspace;

  if (view === 'inbox') return null;

  return (
    <section className="workspace-panel">
      <div className="workspace-head">
        <div>
          <h2>{title}</h2>
          <p>{selectedBusiness.business_name || w.liveWorkspace}</p>
        </div>
        <button className="panel-btn" onClick={onRefresh}>{w.refresh}</button>
      </div>

      {view === 'insights' && (
        <InsightsDashboard conversations={conversations} stats={stats} w={w} />
      )}

      {view === 'leads' && (
        <LeadsBoard
          conversations={conversations}
          leadStages={leadStages}
          leadPrices={leadPrices}
          setLeadStage={onLeadStageChange}
          setLeadPrice={onLeadPriceChange}
          onOpenConversation={onOpenConversation}
          w={w}
        />
      )}

      {view === 'clients' && (
        <ClientsTable
          conversations={conversations}
          leadStages={leadStages}
          leadPrices={leadPrices}
          onOpenConversation={onOpenConversation}
          w={w}
        />
      )}

      {view === 'operators' && (
        <OperatorsSection
          conversations={conversations}
          leadStages={leadStages}
          leadPrices={leadPrices}
          selectedBusinessId={selectedBusinessId}
          operatorDeals={operatorDeals}
          adminNotes={adminNotes}
          operatorAccounts={operatorAccounts}
          onReloadOperatorAccounts={onReloadOperatorAccounts}
          onAdminNote={onAdminNote}
          setOperatorDealCount={onOperatorDealChange}
          setLeadStage={onLeadStageChange}
          setLeadPrice={onLeadPriceChange}
          onOpenConversation={onOpenConversation}
          currentUser={currentUser}
          w={w}
        />
      )}

      {view === 'accounts' && (
        <div className="account-list">
          {businesses.map(b => (
            <button key={b.id} className={`account-row ${b.id === selectedBusinessId ? 'active' : ''}`} onClick={() => onSelectBusiness(b.id)}>
              <Avatar data={avatarFor(b.business_name || b.instagram_business_id || 'Business', b.id)} size={38} platform={b.oauth_provider === 'whatsapp' ? 'whatsapp' : 'instagram'} />
              <span>
                <strong>{b.business_name || w.unnamedBusiness}</strong>
                <em>{b.oauth_provider || b.business_type || 'business'} · {b.bot_enabled ? w.active : w.paused}</em>
              </span>
            </button>
          ))}
          {!businesses.length && <div className="empty">{w.noBusinesses}</div>}
          <BusinessChannelsManager selectedBusiness={selectedBusiness} onToast={onToast} />
        </div>
      )}

      {view === 'knowledge' && (
        <div className="knowledge-view">
          {['products', 'prices', 'delivery_info', 'working_hours', 'faq', 'catalog_link', 'sales_phone', 'knowledge'].map(key => (
            <label key={key}>
              <span>{w[key] || key.replaceAll('_', ' ')}</span>
              <textarea
                value={selectedBusiness[key] || ''}
                onChange={(e) => onBusinessSetting(selectedBusiness.id, { [key]: e.target.value }, false)}
                onBlur={(e) => onBusinessSetting(selectedBusiness.id, { [key]: e.target.value }, true)}
                rows={key === 'knowledge' || key === 'faq' ? 4 : 2}
              />
            </label>
          ))}
        </div>
      )}

      {view === 'prompts' && (
        <div className="settings-view prompt-settings-view">
          <div className="settings-section">
            <h3>{w.globalPrompt}</h3>
            <PromptGeneratorField
              field="global_prompt"
              label={w.usedBy}
              value={promptSettings.global_prompt}
              rows={7}
              businessId={selectedBusiness.id}
              onChange={(value) => onPromptSetting('global_prompt', value)}
              onGeneratePrompt={onGeneratePrompt}
              generatorState={generatorState}
              w={w}
            />
          </div>

          <div className="settings-section">
            <h3>{w.platformOverrides}</h3>
            <PromptGeneratorField
              field="instagram_prompt"
              label={w.instagramRules}
              value={promptSettings.instagram_prompt}
              businessId={selectedBusiness.id}
              onChange={(value) => onPromptSetting('instagram_prompt', value)}
              onGeneratePrompt={onGeneratePrompt}
              generatorState={generatorState}
              w={w}
            />
            <PromptGeneratorField
              field="telegram_prompt"
              label={w.telegramRules}
              value={promptSettings.telegram_prompt}
              businessId={selectedBusiness.id}
              onChange={(value) => onPromptSetting('telegram_prompt', value)}
              onGeneratePrompt={onGeneratePrompt}
              generatorState={generatorState}
              w={w}
            />
            <PromptGeneratorField
              field="whatsapp_prompt"
              label={w.whatsappRules}
              value={promptSettings.whatsapp_prompt}
              businessId={selectedBusiness.id}
              onChange={(value) => onPromptSetting('whatsapp_prompt', value)}
              onGeneratePrompt={onGeneratePrompt}
              generatorState={generatorState}
              w={w}
            />
          </div>

          <div className="settings-section">
            <h3>{w.businessKnowledge}</h3>
            <p className="section-hint">{w.knowledgeHint}</p>
            <div className="prompt-knowledge-grid">
              <span>{w.products}</span>
              <span>{w.prices}</span>
              <span>{w.delivery}</span>
              <span>{w.faq}</span>
              <span>{w.contacts}</span>
              <span>{w.catalogLinks}</span>
            </div>
          </div>

          <div className="settings-section">
            <h3>{w.salesBehavior}</h3>
            <PromptGeneratorField
              field="opening_message"
              label={w.openingMessage}
              value={promptSettings.opening_message}
              rows={4}
              businessId={selectedBusiness.id}
              onChange={(value) => onPromptSetting('opening_message', value)}
              onGeneratePrompt={onGeneratePrompt}
              generatorState={generatorState}
              w={w}
            />
            <PromptGeneratorField
              field="lead_collection_rules"
              label={w.leadCollectionRules}
              value={promptSettings.lead_collection_rules}
              businessId={selectedBusiness.id}
              onChange={(value) => onPromptSetting('lead_collection_rules', value)}
              onGeneratePrompt={onGeneratePrompt}
              generatorState={generatorState}
              w={w}
            />
            <PromptGeneratorField
              field="sales_rules"
              label={w.followUpStyle}
              value={promptSettings.sales_rules}
              businessId={selectedBusiness.id}
              onChange={(value) => onPromptSetting('sales_rules', value)}
              onGeneratePrompt={onGeneratePrompt}
              generatorState={generatorState}
              w={w}
            />
            <PromptGeneratorField
              field="handoff_rules"
              label={w.humanHandoffRules}
              value={promptSettings.handoff_rules}
              businessId={selectedBusiness.id}
              onChange={(value) => onPromptSetting('handoff_rules', value)}
              onGeneratePrompt={onGeneratePrompt}
              generatorState={generatorState}
              w={w}
            />
          </div>

          <div className="panel-actions">
            <button disabled={promptLoading || promptSaving || !selectedBusiness.id} onClick={onSavePromptSettings}>
              {promptSaving ? w.saving : w.savePromptSettings}
            </button>
            <button onClick={() => onToast('Final prompt = Global prompt + Business knowledge + Platform-specific prompt + Conversation memory')}>
              {w.promptFormula}
            </button>
          </div>
        </div>
      )}

      {view === 'settings' && (
        <div className="settings-view">
          <ToggleRow
            label={w.botEnabled}
            hint={w.botEnabledHint}
            checked={!!selectedBusiness.bot_enabled}
            onChange={(enabled) => onBusinessSetting(selectedBusiness.id, { bot_enabled: enabled }, true)}
            w={w}
          />
          <ToggleRow
            label={w.instagramDms}
            hint={w.instagramDmsHint}
            checked={selectedBusiness.auto_reply_dms !== false}
            onChange={(enabled) => onBusinessSetting(selectedBusiness.id, { auto_reply_dms: enabled }, true)}
            w={w}
          />
          <ToggleRow
            label={w.instagramComments}
            hint={w.instagramCommentsHint}
            checked={selectedBusiness.auto_reply_comments !== false}
            onChange={(enabled) => onBusinessSetting(selectedBusiness.id, { auto_reply_comments: enabled }, true)}
            w={w}
          />
          <label className="field-row">
            <span>{w.language}</span>
            <input value={selectedBusiness.language || ''} onChange={(e) => onBusinessSetting(selectedBusiness.id, { language: e.target.value }, false)} onBlur={(e) => onBusinessSetting(selectedBusiness.id, { language: e.target.value }, true)} />
          </label>
          <label className="field-row">
            <span>{w.tone}</span>
            <input value={selectedBusiness.tone || ''} onChange={(e) => onBusinessSetting(selectedBusiness.id, { tone: e.target.value }, false)} onBlur={(e) => onBusinessSetting(selectedBusiness.id, { tone: e.target.value }, true)} />
          </label>
          <div className="settings-section">
            <h3>{w.aiModel}</h3>
            <div className="model-grid">
              <label className="field-row">
                <span>{w.provider}</span>
                <select
                  value={activeProvider.id}
                  onChange={(e) => {
                    const provider = AI_PROVIDERS.find(item => item.id === e.target.value) || AI_PROVIDERS[0];
                    onBusinessSetting(selectedBusiness.id, { ai_model: provider.defaultModel }, true);
                  }}
                >
                  {AI_PROVIDERS.map(provider => (
                    <option key={provider.id} value={provider.id}>{provider.label}</option>
                  ))}
                </select>
              </label>
              <label className="field-row">
                <span>{w.model}</span>
                <select
                  value={modelSelectValue}
                  onChange={(e) => {
                    if (e.target.value === 'custom') return;
                    onBusinessSetting(selectedBusiness.id, { ai_model: e.target.value }, true);
                  }}
                >
                  {activeProvider.models.map(model => (
                    <option key={model} value={model}>{model}</option>
                  ))}
                  <option value="custom">{w.customModel}</option>
                </select>
              </label>
            </div>
            <label className="field-row">
              <span>{w.customModel}</span>
              <input
                value={activeModel}
                onChange={(e) => onBusinessSetting(selectedBusiness.id, { ai_model: e.target.value }, false)}
                onBlur={(e) => onBusinessSetting(selectedBusiness.id, { ai_model: e.target.value.trim() || activeProvider.defaultModel }, true)}
              />
            </label>
            <div className="model-grid">
              <label className="field-row">
                <span>{w.temperature}</span>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.1"
                  value={selectedBusiness.ai_temperature ?? 0.5}
                  onChange={(e) => onBusinessSetting(selectedBusiness.id, { ai_temperature: e.target.value }, false)}
                  onBlur={(e) => onBusinessSetting(selectedBusiness.id, { ai_temperature: Number(e.target.value || 0.5) }, true)}
                />
              </label>
              <label className="field-row">
                <span>{w.maxTokens}</span>
                <input
                  type="number"
                  min="50"
                  max="1000"
                  step="10"
                  value={selectedBusiness.ai_max_tokens ?? 130}
                  onChange={(e) => onBusinessSetting(selectedBusiness.id, { ai_max_tokens: e.target.value }, false)}
                  onBlur={(e) => onBusinessSetting(selectedBusiness.id, { ai_max_tokens: Number(e.target.value || 130) }, true)}
                />
              </label>
            </div>
            <p className="section-hint">
              {w.modelHint || 'Provider, model, temperature, and API keys stay here. Sales prompts now live in AI Prompt Settings so Instagram, Telegram, and WhatsApp share one source of truth.'}
            </p>
          </div>
          <div className="settings-section">
            <h3>{w.apiKeys}</h3>
            <div className="key-grid">
              {AI_PROVIDERS.map(provider => (
                <SecretField
                  key={provider.id}
                  business={selectedBusiness}
	                  provider={provider}
	                  onBusinessSetting={onBusinessSetting}
	                  w={w}
	                />
              ))}
            </div>
          </div>
        </div>
      )}

      {view === 'settings' && !isOperator && (
        <OperatorAccountsPanel
          selectedBusinessId={selectedBusinessId}
          onToast={onToast}
          w={w}
          operatorsData={operatorAccounts}
          onReload={onReloadOperatorAccounts}
        />
      )}

      {view === 'profile' && (
        <div className="settings-view">
          <label className="field-row">
            <span>Display name</span>
            <input
              value={userProfile?.name || ''}
              placeholder="Your name"
              onChange={(e) => onUpdateUserProfile({ name: e.target.value })}
            />
          </label>
          <label className="field-row">
            <span>Photo URL</span>
            <input
              value={userProfile?.photo || ''}
              placeholder="https://..."
              onChange={(e) => onUpdateUserProfile({ photo: e.target.value })}
            />
          </label>
          <div className="metric-card">
            <span>Profile preview</span>
            <b style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="av" style={{ width: 28, height: 28, fontSize: 12 }}>
                {userProfile?.photo ? <img src={userProfile.photo} alt={userProfile?.name || 'Profile'} /> : initialsFromName(userProfile?.name || '')}
              </span>
              {userProfile?.name || 'User'}
            </b>
          </div>
          <div className="metric-card"><span>API base</span><b>{API_BASE}</b></div>
          <label className="field-row">
            <span>Business owner email</span>
            <input
              defaultValue={ownerEmail || ''}
              placeholder="owner@business.com"
              onBlur={(e) => onOwnerEmailSave(e.target.value)}
            />
          </label>
          <div className="panel-actions">
            <button onClick={() => navigator.clipboard?.writeText(API_BASE).then(() => onToast('API base copied'))}>Copy API base</button>
            <button onClick={onSignOut}>Sign out</button>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------- Rail ----------
function Rail({ t, activeView, onView, currentUser, userProfile }) {
  const isOperator = currentUser?.role === 'operator' && currentUser?.isAdmin !== true;
  const items = [
    { id: 'leads', icon: <I.Star />, label: t.leads || 'Leads' },
    { id: 'inbox', icon: <I.Inbox />, label: t.inbox, dot: true },
    { id: 'clients', icon: <I.Comment />, label: t.clients || 'Clients' },
    { id: 'operators', icon: <I.Phone />, label: t.operators || 'Operators' },
    { id: 'knowledge', icon: <I.Book />, label: t.knowledge },
    { id: 'prompts', icon: <I.Sparkle />, label: t.prompts || 'AI Prompts' },
    { id: 'accounts', icon: <I.Layers />, label: t.accounts },
  ].filter(item => !isOperator || ['leads', 'inbox', 'operators'].includes(item.id));
  return (
    <aside className="rail">
      {items.map(it => (
        <button key={it.id} className={`rail-btn ${activeView === it.id ? 'active' : ''}`} title={it.label} onClick={() => onView(it.id)}>
          {it.icon}
          <span className="rail-label">{it.label}</span>
          {it.dot && <span className="dot" />}
        </button>
      ))}
      <div className="rail-spacer" />
      <button className={`rail-btn ${activeView === 'settings' ? 'active' : ''}`} title={t.settings} onClick={() => onView('settings')}>
        <I.Sett />
        <span className="rail-label">{t.settings}</span>
      </button>
      <button className={`rail-btn ${activeView === 'profile' ? 'active' : ''}`} title={t.you || 'You'} onClick={() => onView('profile')}>
        <span className="rail-avatar-mini">
          {userProfile?.photo ? <img src={userProfile.photo} alt={userProfile?.name || 'You'} /> : initialsFromName(userProfile?.name || 'You')}
        </span>
        <span className="rail-label">{t.you || 'You'}</span>
      </button>
      {!isOperator && (
        <button className={`rail-btn ${activeView === 'insights' ? 'active' : ''}`} title={t.insights} onClick={() => onView('insights')}>
          <I.Chart />
          <span className="rail-label">{t.insights}</span>
        </button>
      )}
    </aside>
  );
}

// ---------- Conversation row ----------
function Row({ c, selected, onClick, t }) {
  const isUnread = c.unread > 0;
  return (
    <div className={`row ${selected ? 'selected' : ''}`} onClick={onClick}>
      <Avatar data={c.avatar} platform={c.platform} />
      <div className="row-body">
        <div className="row-line1">
          <span className="row-name">{c.name}</span>
          <span className="row-handle">·  {c.handle}</span>
        </div>
        <div className={`row-preview ${isUnread ? 'unread' : ''}`}>
          {c.lastFromMe && <span className="me">{t.you} · </span>}
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.preview}</span>
        </div>
      </div>
      <div className="row-meta">
        <span className={`row-time ${isUnread ? 'unread' : ''}`}>{c.lastTime}</span>
        <div className="row-badges">
          {c.needsHuman && <span className="chip human">{t.needs.toLowerCase()}</span>}
          {!c.needsHuman && c.aiOn && <span className="chip ai">AI</span>}
          {isUnread && <span className="chip unread">{c.unread}</span>}
        </div>
      </div>
    </div>
  );
}

// ---------- List column ----------
function ListColumn({ conversations, selectedId, onSelect, t, loading, apiError, liveMode, onRefresh }) {
  const [filter, setFilter] = useState('all');
  const [platforms, setPlatforms] = useState({ instagram: true, telegram: true, whatsapp: true });
  const [instagramChannels, setInstagramChannels] = useState({ dm: true, comments: true });
  const [search, setSearch] = useState('');
  const showLoadingState = loading && conversations.length === 0;

  const counts = useMemo(() => ({
    all: conversations.length,
    needs: conversations.filter(c => c.needsHuman).length,
    unread: conversations.filter(c => c.unread > 0).length,
    ai: conversations.filter(c => c.aiOn && !c.needsHuman).length,
  }), [conversations]);

  const filtered = useMemo(() => {
    return conversations.filter(c => {
      if (!platforms[c.platform]) return false;
      if (c.platform === 'instagram') {
        const isComment = Boolean(c.isCommentThread || String(c.channel || '').toLowerCase().includes('comment'));
        if (isComment && !instagramChannels.comments) return false;
        if (!isComment && !instagramChannels.dm) return false;
      }
      if (filter === 'needs' && !c.needsHuman) return false;
      if (filter === 'unread' && c.unread === 0) return false;
      if (filter === 'ai' && (!c.aiOn || c.needsHuman)) return false;
      if (search) {
        const q = search.toLowerCase();
        if (!`${c.name} ${c.handle} ${c.preview}`.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [conversations, filter, platforms, search]);

  const priority = filtered.filter(c => c.needsHuman || c.unread > 0);
  const rest = filtered.filter(c => !c.needsHuman && c.unread === 0);

  return (
    <section className="list-col">
      <div className="list-head">
        <div className={`api-strip ${liveMode ? 'live' : 'mock'}`}>
          <span>{liveMode || conversations.length > 0 ? t.liveBackend : (showLoadingState ? 'Loading... please wait' : 'Waiting for live data')}</span>
          <button onClick={onRefresh} title={t.refresh}>{loading ? t.syncing : t.refresh}</button>
        </div>
        {apiError && <div className="api-error">{apiError}</div>}
        <div className="search">
          <I.Search />
          <input
            placeholder={t.search}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <kbd>⌘K</kbd>
        </div>
        <div className="filters">
          <button className={`filter ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>
            {t.all} <span className="num">{counts.all}</span>
          </button>
          <button className={`filter warn ${filter === 'needs' ? 'active' : ''}`} onClick={() => setFilter('needs')}>
            {t.needs} <span className="num">{counts.needs}</span>
          </button>
          <button className={`filter ${filter === 'unread' ? 'active' : ''}`} onClick={() => setFilter('unread')}>
            {t.unread} <span className="num">{counts.unread}</span>
          </button>
          <button className={`filter ${filter === 'ai' ? 'active' : ''}`} onClick={() => setFilter('ai')}>
            {t.aiHandled} <span className="num">{counts.ai}</span>
          </button>
        </div>
        <div className="platform-toggle">
          <button className={platforms.instagram ? 'on' : ''} onClick={() => setPlatforms(p => ({ ...p, instagram: !p.instagram }))}>
            <span className="pdot ig" /> {t.instagram}
          </button>
          <button className={platforms.telegram ? 'on' : ''} onClick={() => setPlatforms(p => ({ ...p, telegram: !p.telegram }))}>
            <span className="pdot tg" /> {t.telegram}
          </button>
          <button className={platforms.whatsapp ? 'on' : ''} onClick={() => setPlatforms(p => ({ ...p, whatsapp: !p.whatsapp }))}>
            <span className="pdot wa" /> {t.whatsapp}
          </button>
        </div>
        {platforms.instagram && (
          <div className="platform-toggle" style={{ marginTop: 8 }}>
            <button className={instagramChannels.dm ? 'on' : ''} onClick={() => setInstagramChannels(v => ({ ...v, dm: !v.dm }))}>Instagram DMs</button>
            <button className={instagramChannels.comments ? 'on' : ''} onClick={() => setInstagramChannels(v => ({ ...v, comments: !v.comments }))}>Instagram comments</button>
          </div>
        )}
      </div>
      <div className="list-scroll">
        {priority.length > 0 && (
          <>
            <div className="list-section">{t.priority} <em>· {priority.length}</em></div>
            {priority.map(c => (
              <Row key={c.id} c={c} selected={c.id === selectedId} onClick={() => onSelect(c.id)} t={t} />
            ))}
          </>
        )}
        {rest.length > 0 && (
          <>
            <div className="list-section">{t.everything}</div>
            {rest.map(c => (
              <Row key={c.id} c={c} selected={c.id === selectedId} onClick={() => onSelect(c.id)} t={t} />
            ))}
          </>
        )}
        {filtered.length === 0 && (
          showLoadingState ? (
            <div className="loading-state" role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" />
              <p>Loading... please wait</p>
            </div>
          ) : (
            <div className="empty">{t.noConversations}</div>
          )
        )}
      </div>
    </section>
  );
}

// ---------- Voice wave (decorative) ----------
function VoiceWave({ count = 28 }) {
  const heights = useMemo(() => Array.from({ length: count }, (_, i) => {
    const v = 4 + Math.abs(Math.sin(i * 0.7) + Math.cos(i * 0.3)) * 7;
    return Math.min(18, Math.max(3, v));
  }), [count]);
  return (
    <div className="voice-wave">
      {heights.map((h, i) => <i key={i} style={{ height: h }} />)}
    </div>
  );
}

// ---------- Message bubble ----------
function Message({ m, conv, t, onReplyComment }) {
  if (m.side === 'system' && m.type === 'handoff') {
    return (
      <div className="handoff-banner">
        <div className="icon"><I.AlertTri /></div>
        <div className="text">
          <strong>{t.handoffTitle}</strong>
          <span>{m.text}</span>
        </div>
      </div>
    );
  }
  const fromAi = m.from === 'ai';
  const canReplyToComment = Boolean(
    conv?.isCommentThread &&
    m.side === 'inbound' &&
    m.commentId &&
    typeof onReplyComment === 'function'
  );
  return (
    <div className={`msg-group ${m.side} ${fromAi ? 'from-ai' : ''}`}>
      {m.type === 'text' && (
        <div className="bubble">{m.text}</div>
      )}
      {m.type === 'media' && (
        <div className="bubble media">
          {m.mediaKind === 'video' && isPlayableVideoUrl(m.mediaUrl) ? (
            <video className="media-video" src={m.mediaUrl} controls />
          ) : m.mediaUrl && (m.mediaKind === 'photo' || isRenderableImageUrl(m.mediaUrl)) && !isInstagramPostLink(m.mediaUrl) ? (
            <img className="media-img" src={m.mediaUrl} alt={m.label || 'attachment'} />
          ) : m.mediaKind === 'file' && m.mediaUrl && !isInstagramPostLink(m.mediaUrl) ? (
            <a className="file-chip" href={m.mediaUrl} target="_blank" rel="noreferrer">
              <I.Paperclip />
              <span>{m.label || 'open file'}</span>
            </a>
          ) : m.mediaKind === 'file' ? (
            <div className="file-chip">
              <I.Paperclip />
              <span>{m.label || 'document'}</span>
            </div>
          ) : m.mediaUrl ? (
            <a className="file-chip" href={m.mediaUrl} target="_blank" rel="noreferrer">
              <I.Paperclip />
              <span>{m.label || 'open media'}</span>
            </a>
          ) : (
            <span className="ph" data-label={m.label || 'photo'} />
          )}
          {m.mediaCaption && <div className="cap">{m.mediaCaption}</div>}
          {m.forwardLink && conv?.platform === 'instagram' && (
            <a className="open-post-link" href={m.forwardLink} target="_blank" rel="noreferrer">
              Open on Instagram
            </a>
          )}
          {!m.mediaUrl && m.mediaFileId && <div className="media-note">Media ID saved. Preview needs backend media download URL.</div>}
        </div>
      )}
      {m.type === 'voice' && (
        <div className="bubble voice">
          <button className="tool-btn" style={{ background: 'rgba(255,255,255,.1)' }}><I.Mic /></button>
          {m.mediaUrl ? <audio className="voice-player" src={m.mediaUrl} controls /> : <VoiceWave />}
          <span className="voice-time">{m.duration || '0:12'}</span>
        </div>
      )}
      {m.type === 'catalog' && (
        <div className="bubble catalog">
          <div className="catalog-body">{m.catalogText}</div>
          <a className="catalog-btn">{m.catalogLabel} →</a>
        </div>
      )}
      <div className="msg-meta">
        {fromAi && <span className="ai-mark">auto</span>}
        <span>{m.time}</span>
        {m.side === 'outbound' && <span className="check"><I.DoubleCheck /></span>}
      </div>
      {canReplyToComment && (
        <button
          type="button"
          className="msg-reply-btn"
          onClick={() => onReplyComment(m)}
        >
          Reply
        </button>
      )}
    </div>
  );
}

// ---------- Thread head ----------
function ThreadHead({ conv, aiOn, onToggleAi, t, onPin, onArchive, onDelete, onMore, moreOpen }) {
  if (!conv) return null;
  return (
    <div className="topbar-thread">
      <div className="thread-head-info">
        <Avatar data={conv.avatar} platform={conv.platform} size={36} />
        <div className="info-text">
          <div className="name">{conv.name}</div>
          <div className="sub">
            {conv.online && <span className="fixed online-dot" />}
            <span className="fixed">{conv.handle}</span>
            <span className="fixed dot" />
            <span>{conv.location}</span>
          </div>
        </div>
      </div>
      <div className="thread-actions">
        <button className={`ai-toggle ${aiOn ? 'on' : ''}`} onClick={onToggleAi}>
          <span className="switch" />
          <span className="label-i">{aiOn ? t.aiOn : t.aiOff}</span>
        </button>
        <button className={`icon-btn ${conv.pinned ? 'active' : ''}`} title="Pin" onClick={onPin}><I.Star /></button>
        <button className="icon-btn" title="Archive" onClick={onArchive}><I.Archive /></button>
        <div className="menu-wrap">
          <button className="icon-btn" title="More" onClick={onMore}><I.Dots /></button>
          {moreOpen && (
            <div className="pop-menu thread-menu">
              <button onClick={onPin}>{conv.pinned ? 'Unpin chat' : 'Pin chat'}</button>
              <button onClick={() => navigator.clipboard?.writeText(conv.customerId)}>Copy customer ID</button>
              <button onClick={onArchive}>Archive locally</button>
              <button className="danger" onClick={onDelete}>{t.deleteChat}</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------- Thread column ----------
function ThreadColumn({ conv, aiOn, onToggleAi, t, messages, onSend, sending, threadLoading, onTool }) {
  if (!conv) {
    return <section className="thread-col" />;
  }
  const scrollRef = useRef(null);
  const imageInputRef = useRef(null);
  const attachInputRef = useRef(null);
  const composerRef = useRef(null);
  const emojiPanelRef = useRef(null);
  const emojiToggleRef = useRef(null);
  const recorderRef = useRef(null);
  const recordingChunksRef = useRef([]);
  const recordingStreamRef = useRef(null);
  const recordingShouldSendRef = useRef(true);
  const [draft, setDraft] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(true);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordingStartedAt, setRecordingStartedAt] = useState(0);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [replyTarget, setReplyTarget] = useState(null);
  const voiceRecordingSupported = ['telegram', 'whatsapp'].includes(conv.platform);

  const sendDraft = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft('');
    const sent = await onSend(text, { replyToCommentId: replyTarget?.commentId || '' });
    if (sent !== false) setReplyTarget(null);
  };

  const selectReplyTarget = (message) => {
    if (!message?.commentId) return;
    const preview = String(message.text || message.mediaCaption || '').trim();
    setReplyTarget({
      commentId: message.commentId,
      preview: preview || '[comment]',
    });
    requestAnimationFrame(() => composerRef.current?.focus());
  };

  const uploadImage = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const sent = await onTool('photo', setDraft, file, draft);
    if (sent) setDraft('');
  };

  const insertEmoji = (emoji) => {
    setDraft(current => `${current}${current && !current.endsWith(' ') ? ' ' : ''}${emoji}`);
    setEmojiOpen(false);
  };

  const stopRecordingTracks = () => {
    recordingStreamRef.current?.getTracks().forEach(track => track.stop());
    recordingStreamRef.current = null;
  };

  const startVoiceRecording = async () => {
    if (sending || recording) return;

    if (!voiceRecordingSupported) {
      await onTool('voice-instagram', setDraft);
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      await onTool('voice-unsupported', setDraft);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = recordingMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);

      recordingChunksRef.current = [];
      recordingShouldSendRef.current = true;
      recordingStreamRef.current = stream;
      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) recordingChunksRef.current.push(event.data);
      };

      recorder.onstop = async () => {
        const shouldSend = recordingShouldSendRef.current;
        const chunks = recordingChunksRef.current;
        const finalMimeType = recorder.mimeType || mimeType || 'audio/webm';

        setRecording(false);
        setRecordingStartedAt(0);
        setRecordingSeconds(0);
        stopRecordingTracks();

        if (!shouldSend || !chunks.length) return;

        const blob = new Blob(chunks, { type: finalMimeType });
        const file = new File(
          [blob],
          `voice-${Date.now()}.${extensionForMime(finalMimeType)}`,
          { type: finalMimeType },
        );
        await onTool('voice', setDraft, file);
      };

      recorder.start();
      setRecording(true);
      setRecordingStartedAt(Date.now());
      setRecordingSeconds(0);
    } catch (error) {
      stopRecordingTracks();
      await onTool('voice-permission', setDraft, null, error?.message || '');
    }
  };

  const stopVoiceRecording = () => {
    if (!recording || !recorderRef.current) return;
    recordingShouldSendRef.current = true;
    recorderRef.current.stop();
  };

  const cancelVoiceRecording = () => {
    if (!recording || !recorderRef.current) return;
    recordingShouldSendRef.current = false;
    recorderRef.current.stop();
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.style.scrollBehavior = 'auto';
    const scroll = () => { el.scrollTop = el.scrollHeight; };
    scroll();
    const r1 = requestAnimationFrame(scroll);
    const r2 = requestAnimationFrame(() => requestAnimationFrame(scroll));
    const t1 = setTimeout(scroll, 100);
    const t2 = setTimeout(scroll, 400);
    const t3 = setTimeout(() => { el.style.scrollBehavior = 'smooth'; }, 500);
    setDraft('');
    setReplyTarget(null);
    return () => {
      cancelAnimationFrame(r1); cancelAnimationFrame(r2);
      clearTimeout(t1); clearTimeout(t2); clearTimeout(t3);
    };
  }, [conv.id]);

  useEffect(() => {
    if (!recording) return undefined;
    const timer = window.setInterval(() => {
      setRecordingSeconds(Math.max(0, Math.floor((Date.now() - recordingStartedAt) / 1000)));
    }, 250);
    return () => window.clearInterval(timer);
  }, [recording, recordingStartedAt]);

  useEffect(() => () => {
    recordingShouldSendRef.current = false;
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
    stopRecordingTracks();
  }, []);

  useEffect(() => {
    if (!emojiOpen) return undefined;

    const closeOnOutsideTouch = (event) => {
      const target = event.target;
      if (!target) return;
      if (emojiPanelRef.current?.contains(target)) return;
      if (emojiToggleRef.current?.contains(target)) return;
      setEmojiOpen(false);
    };

    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setEmojiOpen(false);
    };

    document.addEventListener('pointerdown', closeOnOutsideTouch, true);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideTouch, true);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [emojiOpen]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const last = messages[messages.length - 1];
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom > 240 && last?.side !== 'outbound') return;
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    });
  }, [messages.length, conv.id]);

  // Group consecutive same-side messages for tight bubble corners
  const groups = useMemo(() => {
    const out = [];
    let lastSide = null;
    for (const m of messages) {
      if (m.side === 'system') { out.push(m); lastSide = null; continue; }
      const same = m.side === lastSide;
      out.push({ ...m, same });
      lastSide = m.side;
    }
    return out;
  }, [messages]);
  const commentPost = useMemo(() => resolveCommentPostPreview(conv, messages), [conv, messages]);

  let lastDay = null;

  return (
    <section className="thread-col">
      <div className="messages" ref={scrollRef}>
        {threadLoading && <div className="empty">Loading conversation…</div>}
        {conv.isCommentThread && (commentPost.postImageUrl || commentPost.postPermalink || commentPost.postId) && (
          <div className="post-preview-card">
            {commentPost.postImageUrl && isVideoPostPreview(commentPost) ? (
              <video
                className="post-preview-video"
                src={commentPost.postImageUrl}
                controls
                playsInline
                preload="metadata"
              />
            ) : commentPost.postImageUrl ? (
              <img className="post-preview-image" src={commentPost.postImageUrl} alt="Instagram post" />
            ) : (
              <div className="post-preview-fallback">Instagram post</div>
            )}
            <div className="post-preview-meta">
              <strong>Commented post</strong>
              {commentPost.postPermalink ? (
                <a href={commentPost.postPermalink} target="_blank" rel="noreferrer">Open on Instagram</a>
              ) : (
                <span>ID: {commentPost.postId || 'unknown'}</span>
              )}
            </div>
          </div>
        )}
        {groups.map(m => {
          const dayChanged = m.day && m.day !== lastDay;
          if (m.day) lastDay = m.day;
          return (
            <React.Fragment key={m.id}>
              {dayChanged && <div className="day-sep">{m.day}</div>}
              <Message m={m} conv={conv} t={t} onReplyComment={selectReplyTarget} />
            </React.Fragment>
          );
        })}
        {aiOn && conv.needsHuman === false && (
          <div className="ai-banner">
            <I.Sparkle />
            <span><em>AI</em> is keeping this chat warm. Start typing to take over.</span>
          </div>
        )}
      </div>

      {/* Suggested replies */}
      {showSuggestions && conv.suggestions && conv.suggestions.length > 0 && (
        <div className="suggest-row">
          <span className="label">{t.suggested}</span>
          {conv.suggestions.map((s, i) => (
            <button key={i} className="suggestion" onClick={() => setDraft(s)}>{s}</button>
          ))}
        </div>
      )}

      <div className="composer">
        <div className="composer-card">
          {replyTarget?.commentId && (
            <div className="reply-target-bar">
              <span>Replying to: {replyTarget.preview.slice(0, 90)}</span>
              <button type="button" onClick={() => setReplyTarget(null)}>Cancel</button>
            </div>
          )}
          <input
            ref={imageInputRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={uploadImage}
          />
          <input
            ref={attachInputRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={uploadImage}
          />
          <textarea
            ref={composerRef}
            className="composer-input"
            placeholder={`${t.typing} ${conv.name.split(' ')[0]}…`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={1}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendDraft();
              }
            }}
          />
          <div className="composer-bar">
            <button className="tool-btn" title="Attach image" disabled={sending} onClick={() => attachInputRef.current?.click()}><I.Paperclip /></button>
            <button className="tool-btn" title="Photo" disabled={sending} onClick={() => imageInputRef.current?.click()}><I.Photo /></button>
            <button
              className={`tool-btn ${recording ? 'recording active' : ''} ${!voiceRecordingSupported ? 'unsupported' : ''}`}
              title={voiceRecordingSupported ? (recording ? 'Stop and send voice' : 'Record voice') : 'Voice recording unavailable for Instagram'}
              disabled={sending}
              onClick={recording ? stopVoiceRecording : startVoiceRecording}
            >
              <I.Mic />
            </button>
            <button
              ref={emojiToggleRef}
              className={`tool-btn ${emojiOpen ? 'active' : ''}`}
              title="Emoji"
              onClick={() => setEmojiOpen(open => !open)}
            >
              <I.Smile />
            </button>
            <div className="grow" />
            <span style={{ fontSize: 11, color: 'var(--muted)', marginRight: 6 }}>{t.kbdHint}</span>
            <button className={`send ${draft.trim() && !sending ? '' : 'disabled'}`} onClick={sendDraft}>
              <I.Send /> {sending ? 'Sending' : t.send}
            </button>
          </div>
          {recording && (
            <div className="recording-strip">
              <span className="record-dot" />
              <span>Recording {formatRecordTime(recordingSeconds)}</span>
              <button type="button" onClick={cancelVoiceRecording}>Cancel</button>
              <button type="button" onClick={stopVoiceRecording}>Send</button>
            </div>
          )}
          {emojiOpen && (
            <div ref={emojiPanelRef} className="emoji-panel">
              {EMOJI_SETS.map(group => (
                <div className="emoji-group" key={group.label}>
                  <div className="emoji-label">{group.label}</div>
                  <div className="emoji-grid">
                    {group.items.map((emoji, index) => (
                      <button
                        key={`${group.label}-${emoji}-${index}`}
                        type="button"
                        className="emoji-cell"
                        onClick={() => insertEmoji(emoji)}
                      >
                        {emoji}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

// ---------- Detail column ----------
function DetailColumn({ conv, t, stats, onDelete, messages = [] }) {
  if (!conv) return <aside className="detail-col" />;
  const commentPost = resolveCommentPostPreview(conv, messages);
  return (
    <aside className="detail-col">
      <div className="cust-card">
        <div className="cust-avatar" style={{ background: conv.avatar.color }}>
          {conv.avatar.initials}
        </div>
        <h2 className="cust-name">{conv.name}</h2>
        <div className="cust-handle">
          <PlatformIcon p={conv.platform} />
          <span>{conv.handle}</span>
          <span style={{ width: 3, height: 3, borderRadius: '50%', background: 'var(--muted)' }} />
          <span>{conv.location}</span>
        </div>
        <div className="cust-meta">
          {conv.tags.map(t => <span key={t} className="tag">{t}</span>)}
          <span className="tag">{t.since} {conv.customerSince}</span>
        </div>
      </div>

      <div className="detail-section">
        <h3>{t.summary} <em>· auto</em></h3>
        <div className="summary">{conv.summary}</div>
      </div>

      <div className="detail-section">
        <h3>{t.channel}</h3>
        {conv.isCommentThread && (commentPost.postImageUrl || commentPost.postPermalink || commentPost.postId) && (
          <div className="detail-post-card">
            {commentPost.postImageUrl && isVideoPostPreview(commentPost) ? (
              <video
                className="detail-post-video"
                src={commentPost.postImageUrl}
                controls
                playsInline
                preload="metadata"
              />
            ) : commentPost.postImageUrl ? (
              <img className="detail-post-image" src={commentPost.postImageUrl} alt="Instagram post" />
            ) : (
              <div className="detail-post-fallback">Instagram post</div>
            )}
            <div className="detail-post-meta">
              <span>Source post</span>
              {commentPost.postPermalink ? (
                <a href={commentPost.postPermalink} target="_blank" rel="noreferrer">Open on Instagram</a>
              ) : (
                <small>ID: {commentPost.postId || 'unknown'}</small>
              )}
            </div>
          </div>
        )}
        <div className="channel-facts">
          <span>{t.platform} <b>{conv.platform}</b></span>
          <span>{t.channel} <b>{conv.channelName || conv.channel || t.inbox}</b></span>
          <span>{t.customer} <b>{conv.customerId}</b></span>
          <span>{t.chat} <b>{conv.chatId || conv.customerId}</b></span>
          <span>{t.sendVia} <b>{sendRouteFor(conv)}</b></span>
        </div>
        <div className="panel-actions compact">
          <button className="danger" onClick={onDelete}>{t.deleteChat}</button>
        </div>
      </div>

      <div className="detail-section">
        <h3>{t.stats}</h3>
        <div className="kpi-row">
          <div className="kpi">
            <div className="label">Messages</div>
            <div className="value">{conv.kpis.orders}</div>
            <div className="delta up">{conv.kpis.last || 'synced'}</div>
          </div>
          <div className="kpi">
            <div className="label">Unread</div>
            <div className="value">{conv.kpis.ltv}</div>
            <div className={`delta ${String(conv.kpis.conv).startsWith('+') ? 'up' : ''}`}>{conv.kpis.conv}</div>
          </div>
        </div>
      </div>

      {stats && (
        <div className="detail-section">
          <h3>Backend</h3>
          <div className="backend-grid">
            <span>Accounts <b>{stats.total_accounts ?? 0}</b></span>
            <span>Active <b>{stats.active_accounts ?? 0}</b></span>
            <span>Instagram <b>{stats.instagram_messages ?? 0}</b></span>
            <span>Telegram <b>{stats.telegram_messages ?? 0}</b></span>
            <span>WhatsApp <b>{stats.whatsapp_messages ?? 0}</b></span>
          </div>
        </div>
      )}

      {conv.orders.length > 0 && (
        <div className="detail-section">
          <h3>{t.orders}</h3>
          {conv.orders.map((o, i) => (
            <div key={i} className="order">
              <div className="ph" />
              <div className="body">
                <div className="t">{o.t}</div>
                <div className="s">{o.s}</div>
              </div>
              <div className="price">{o.price}</div>
            </div>
          ))}
        </div>
      )}

      <div className="detail-section">
        <h3>{t.notes}</h3>
        <div className="note">{t.note}</div>
      </div>
    </aside>
  );
}

// ---------- Top bar ----------
function TopBar({ t, lang, setLang, theme, setTheme, conv, aiOn, activeView, onToggleAi, onRefresh, onToast, onPin, onArchive, onDelete, onMore, moreOpen, onOpenProfile, onSignOut, userProfile, onUpdateUserProfile }) {
  const [accountOpen, setAccountOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const fileInputRef = useRef(null);
  const w = WORKSPACE_TEXT[lang] || WORKSPACE_TEXT.en;
  const workspaceNames = { inbox: t.inbox, insights: t.insights, knowledge: t.knowledge, prompts: w.promptsTitle, accounts: t.accounts, settings: t.settings, profile: w.profile };
  const displayName = String(userProfile?.name || 'User');
  const initials = initialsFromName(displayName);

  const uploadAvatar = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      onToast('Please choose an image file.');
      return;
    }
    if (file.size > 3 * 1024 * 1024) {
      onToast('Image is too large. Max 3 MB.');
      return;
    }
    try {
      const photo = await fileToDataUrl(file);
      onUpdateUserProfile({ photo });
      onToast('Profile photo updated');
      setProfileOpen(false);
    } catch (e) {
      onToast('Could not read this image');
    }
  };

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" />
      </div>
      <div className="topbar-list">
        <span className="wordmark">{t.appName}<em>{t.appNameAccent}</em></span>
        <div className="menu-wrap" style={{ marginLeft: 'auto' }}>
          <button className="acct-pill" title="Switch account" onClick={() => setAccountOpen(v => !v)}>
            <span className="av">L</span>
            <span>{conv?.businessId ? `Business ${String(conv.businessId).slice(0, 4)}` : 'Loomé'}</span>
            <I.Caret />
          </button>
          {accountOpen && (
            <div className="pop-menu account-menu">
              <button onClick={() => { onRefresh(); setAccountOpen(false); }}>Refresh accounts</button>
              <button onClick={() => { window.open(`${API_BASE}/connect-instagram`, '_blank'); setAccountOpen(false); }}>Connect Instagram</button>
              <button onClick={() => { window.open(`${API_BASE}/connect-facebook`, '_blank'); setAccountOpen(false); }}>Connect Facebook</button>
            </div>
          )}
        </div>
      </div>
      {activeView === 'inbox' ? (
        <ThreadHead
          conv={conv}
          aiOn={aiOn}
          onToggleAi={onToggleAi}
          t={t}
          onPin={onPin}
          onArchive={onArchive}
          onDelete={onDelete}
          onMore={onMore}
          moreOpen={moreOpen}
        />
      ) : (
        <div className="topbar-thread workspace-top-title">
          <span>{workspaceNames[activeView] || w.workspace}</span>
        </div>
      )}
      <div className="topbar-right">
        <div className="lang">
          {['en', 'uz', 'ru'].map(l => (
            <button key={l} className={lang === l ? 'on' : ''} onClick={() => setLang(l)}>{l}</button>
          ))}
        </div>
        <button className="theme-btn" title="Theme" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
          {theme === 'dark' ? <I.Sun /> : <I.Moon />}
        </button>
        <button className="icon-btn" title="Notifications" onClick={() => { onRefresh(); onToast('Inbox refreshed'); }} style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8 }}>
          <I.Bell />
        </button>
        <div className="menu-wrap">
          <button className="profile" onClick={() => setProfileOpen(v => !v)}>
            <span className="av">{userProfile?.photo ? <img src={userProfile.photo} alt={displayName} /> : initials}</span>
            <span>{displayName}</span>
            <I.Caret />
          </button>
          {profileOpen && (
            <div className="pop-menu profile-menu">
              <button onClick={() => { onOpenProfile?.(); setProfileOpen(false); }}>Profile settings</button>
              <button onClick={() => fileInputRef.current?.click()}>Change photo</button>
              <button onClick={onSignOut}>Sign out</button>
            </div>
          )}
          <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={uploadAvatar} />
        </div>
      </div>
    </header>
  );
}

// ---------- App root ----------
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "light"
}/*EDITMODE-END*/;

function App({ lang, setLang, onSignOut, currentUser }) {
  const t = window.STRINGS[lang];
  const isOperator = currentUser?.role === 'operator' && currentUser?.isAdmin !== true;
  const [booting, setBooting] = useState(true);

  const [conversations, setConversations] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [threads, setThreads] = useState({});
  const [loading, setLoading] = useState(false);
  const [threadLoading, setThreadLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [apiError, setApiError] = useState('');
  const [liveMode, setLiveMode] = useState(false);
  const [stats, setStats] = useState(null);
  const [activeView, setActiveView] = useState('inbox');
  const [toast, setToast] = useState('');
  const [moreOpen, setMoreOpen] = useState(false);
  const [businesses, setBusinesses] = useState([]);
  const [selectedBusinessId, setSelectedBusinessId] = useState('');
  const [ownerEmail, setOwnerEmail] = useState(resolvedOwnerEmail());
  const [promptSettings, setPromptSettings] = useState({});
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptGeneratorState, setPromptGeneratorState] = useState({});
  const [operatorAccounts, setOperatorAccounts] = useState([]);
  const [leadStages, setLeadStages] = useState(() => readStoredObject(LEAD_STAGES_STORAGE_KEY));
  const [leadPrices, setLeadPrices] = useState(() => readStoredObject(LEAD_PRICES_STORAGE_KEY));
  const [operatorDeals, setOperatorDeals] = useState(() => readStoredObject(OPERATOR_DEALS_STORAGE_KEY));
  const [operatorAdminNotes, setOperatorAdminNotes] = useState(() => {
    const stored = readStoredObject(OPERATOR_ADMIN_NOTES_STORAGE_KEY);
    return Array.isArray(stored.items) ? stored.items : [];
  });
  const [aiOverrides, setAiOverrides] = useState(() => readStoredObject(AI_OVERRIDE_STORAGE_KEY));
  const [deletedConversations, setDeletedConversations] = useState(() => readStoredObject(DELETED_CONVERSATIONS_STORAGE_KEY));
  const [userProfile, setUserProfile] = useState(() => readUserProfile(currentUser));
  const selectedIdRef = useRef(selectedId);
  const liveModeRef = useRef(liveMode);
  const aiOverridesRef = useRef(aiOverrides);
  const deletedConversationsRef = useRef(deletedConversations);
  const threadPollBusy = useRef(false);
  const inboxPollBusy = useRef(false);
  const statsPollBusy = useRef(false);
  const tasksPollBusy = useRef(false);
  const businessesRef = useRef([]);
  const workspaceStateHydratedRef = useRef(false);
  const workspaceStateTimersRef = useRef({});
  const conv = conversations.find(c => c.id === selectedId);
  const aiOn = conv ? conv.aiOn : false;
  const messages = threads[selectedId] || window.getThread(selectedId);

  const [theme, setTheme] = useState(TWEAK_DEFAULTS.theme);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    liveModeRef.current = liveMode;
  }, [liveMode]);

  useEffect(() => {
    aiOverridesRef.current = aiOverrides;
  }, [aiOverrides]);

  useEffect(() => {
    deletedConversationsRef.current = deletedConversations;
  }, [deletedConversations]);

  useEffect(() => {
    setUserProfile(readUserProfile(currentUser));
  }, [currentUser?.ownerEmail, currentUser?.email]);

  const showToast = (message) => {
    setToast(message);
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => setToast(''), 2200);
  };

  const updateUserProfile = (patch = {}) => {
    const next = saveUserProfile(currentUser, patch);
    setUserProfile(next);
  };

  const loadStats = async () => {
    try {
      const data = await API.get('/api/v2/stats');
      setStats(data.data || null);
    } catch (e) {
      setStats(null);
    }
  };

  const loadWorkspaceState = async (businessId = selectedBusinessId) => {
    const business = String(businessId || '').trim();
    if (!business || !liveModeRef.current) return;
    try {
      const response = await API.get(`/api/v2/workspace-state?business_id=${encodeURIComponent(business)}`);
      const state = response?.data || {};
      workspaceStateHydratedRef.current = true;

      if (state.lead_stages && typeof state.lead_stages === 'object') {
        setLeadStages(state.lead_stages);
        writeStoredObject(LEAD_STAGES_STORAGE_KEY, state.lead_stages);
      }
      if (state.lead_prices && typeof state.lead_prices === 'object') {
        setLeadPrices(state.lead_prices);
        writeStoredObject(LEAD_PRICES_STORAGE_KEY, state.lead_prices);
      }
      if (state.operator_deals && typeof state.operator_deals === 'object') {
        setOperatorDeals(state.operator_deals);
        writeStoredObject(OPERATOR_DEALS_STORAGE_KEY, state.operator_deals);
      }
      if (state.operator_admin_notes && typeof state.operator_admin_notes === 'object') {
        const notes = Array.isArray(state.operator_admin_notes.items) ? state.operator_admin_notes.items : [];
        setOperatorAdminNotes(notes);
        writeStoredObject(OPERATOR_ADMIN_NOTES_STORAGE_KEY, { items: notes });
      }
    } catch (e) {
      workspaceStateHydratedRef.current = true;
    }
  };

  const queueWorkspaceStateSave = (statePatch = {}) => {
    if (!liveModeRef.current || !workspaceStateHydratedRef.current) return;
    const business = String(selectedBusinessId || '').trim();
    if (!business) return;

    Object.entries(statePatch).forEach(([key, value]) => {
      window.clearTimeout(workspaceStateTimersRef.current[key]);
      workspaceStateTimersRef.current[key] = window.setTimeout(async () => {
        try {
          await API.postJson('/api/v2/workspace-state', {
            business_id: business,
            state: { [key]: value },
          });
        } catch (e) {
          // Keep local UX fast; backend sync can retry on the next edit.
        }
      }, 450);
    });
  };

  const loadBusinesses = async ({ silent = false, ownerEmailOverride = '' } = {}) => {
    try {
      const data = await API.get('/api/businesses');
      const rows = data.data || [];
      businessesRef.current = rows;
      setBusinesses(rows);
      setSelectedBusinessId(current => rows.some(item => item.id === current) ? current : rows[0]?.id || '');
      return rows;
    } catch (e) {
      if (!silent) showToast(e.message);
      businessesRef.current = [];
      return [];
    }
  };

  const loadPromptSettings = async (businessId = selectedBusinessId, { silent = false } = {}) => {
    if (!businessId) return {};
    setPromptLoading(true);
    try {
      const data = await API.get(`/api/ai-prompt-settings/${encodeURIComponent(businessId)}`);
      const next = data.data || {};
      setPromptSettings(next);
      return next;
    } catch (e) {
      if (!silent) showToast(e.message);
      return {};
    } finally {
      setPromptLoading(false);
    }
  };

  const loadOperatorAccounts = async (businessId = selectedBusinessId) => {
    try {
      const business = String(businessId || '').trim();
      const endpoint = business
        ? `/api/v2/operators?business_id=${encodeURIComponent(business)}`
        : '/api/v2/operators';
      const fallback = await API.get(endpoint);
      const rows = fallback.data || [];
      setOperatorAccounts(rows);
      return rows;
    } catch {
      setOperatorAccounts([]);
      return [];
    }
  };

  const loadOperatorTasks = async (businessId = selectedBusinessId) => {
    const business = String(businessId || '').trim();
    if (!business || !liveModeRef.current) return [];
    try {
      const response = await API.get(`/api/v2/operator-tasks?business_id=${encodeURIComponent(business)}&for_me=true`);
      const rows = Array.isArray(response?.data) ? response.data : [];
      setOperatorAdminNotes(rows);
      writeStoredObject(OPERATOR_ADMIN_NOTES_STORAGE_KEY, { items: rows });
      return rows;
    } catch {
      return [];
    }
  };

  const updatePromptSetting = (key, value) => {
    setPromptSettings(settings => ({ ...settings, [key]: value }));
  };

  const generatePromptSuggestion = async (field, currentPrompt, goal) => {
    const w = WORKSPACE_TEXT[lang] || WORKSPACE_TEXT.en;
    if (goal === 'decline') {
      setPromptGeneratorState(state => ({ ...state, [field]: {} }));
      return;
    }

    if (!selectedBusinessId) {
      const fallback = localPromptSuggestion(field, currentPrompt, goal);
      setPromptGeneratorState(state => ({
        ...state,
        [field]: {
          loading: false,
          suggestedPrompt: fallback.suggested_prompt,
          explanation: `${fallback.explanation} ${w.noBusinessLocal}`,
        },
      }));
      showToast(w.promptLocal);
      return;
    }

    setPromptGeneratorState(state => ({
      ...state,
      [field]: { ...(state[field] || {}), loading: true },
    }));

    try {
      const data = await API.postJson('/api/v2/ai-prompt/generate', {
        business_id: selectedBusinessId,
        field,
        current_prompt: currentPrompt || '',
        goal,
      });
      setPromptGeneratorState(state => ({
        ...state,
        [field]: {
          loading: false,
          suggestedPrompt: data.suggested_prompt || data.data?.suggested_prompt || '',
          explanation: data.explanation || data.data?.explanation || '',
        },
      }));
      showToast(w.promptReady);
    } catch (e) {
      const fallback = localPromptSuggestion(field, currentPrompt, goal);
      setPromptGeneratorState(state => ({
        ...state,
        [field]: {
          loading: false,
          suggestedPrompt: fallback.suggested_prompt,
          explanation: `${fallback.explanation} ${w.backendUnavailableLocal}`,
        },
      }));
      showToast(w.promptLocal);
    }
  };

  const savePromptSettings = async () => {
    if (!selectedBusinessId) {
      showToast('Select a business first');
      return;
    }

    setPromptSaving(true);
    try {
      const data = await API.postJson('/api/ai-prompt-settings', {
        business_id: selectedBusinessId,
        settings: promptSettings,
      });
      setPromptSettings(data.data || promptSettings);
      showToast('AI prompt settings saved');
    } catch (e) {
      setApiError(e.message);
      showToast(e.message);
    } finally {
      setPromptSaving(false);
    }
  };

  const refreshWorkspace = async () => {
    await Promise.all([
      loadConversations({ sideLoad: false }),
      loadStats(),
      loadBusinesses(),
      loadPromptSettings(selectedBusinessId, { silent: true }),
      loadOperatorAccounts(selectedBusinessId),
      loadOperatorTasks(selectedBusinessId),
    ]);
    showToast('Workspace refreshed');
  };

  const rememberAiOverride = (conversationId, enabled) => {
    setAiOverrides(prev => {
      const next = { ...prev, [conversationId]: enabled === true };
      writeStoredObject(AI_OVERRIDE_STORAGE_KEY, next);
      return next;
    });
  };

  const rememberDeletedConversation = (conversationId) => {
    setDeletedConversations(prev => {
      const next = { ...prev, [conversationId]: true };
      writeStoredObject(DELETED_CONVERSATIONS_STORAGE_KEY, next);
      return next;
    });
  };

  const removeConversationFromUi = (conversationId) => {
    setConversations(cs => {
      const next = cs.filter(c => c.id !== conversationId);
      setSelectedId(current => current === conversationId ? next[0]?.id || '' : current);
      return next;
    });
    setThreads(prev => {
      const next = { ...prev };
      delete next[conversationId];
      return next;
    });
  };

  const loadConversations = async ({ sideLoad = true, silent = false, ownerEmailOverride = '' } = {}) => {
    if (!silent) setLoading(true);
    try {
      if (sideLoad || !businessesRef.current.length) {
        await loadBusinesses({ silent: true, ownerEmailOverride });
      }
      const data = await API.get('/api/v2/conversations');
      const selectedCurrent = selectedIdRef.current;
      const ownerScoped = normalizeOwnerEmail(ownerEmailOverride || ownerEmail);
      const allowedBusinessIds = new Set((businessesRef.current || []).map(row => row.id).filter(Boolean));
      const next = (data.data || [])
        .map(normalizeConversation)
        .filter(item => {
          if (allowedBusinessIds.size && item.businessId) return allowedBusinessIds.has(item.businessId);
          if (!ownerScoped) return true;
          return conversationOwnerEmail(item) === ownerScoped;
        })
        .filter(item => !deletedConversationsRef.current[item.id])
        .map(item => Object.prototype.hasOwnProperty.call(aiOverridesRef.current, item.id)
          ? { ...item, aiOn: aiOverridesRef.current[item.id] === true }
          : item)
        .map(item => item.id === selectedCurrent ? clearConversationUnread(item) : item);
      setConversations(next);
      setSelectedId(current => next.some(c => c.id === current) ? current : (next[0]?.id || ''));
      setLiveMode(true);
      setApiError('');
      if (sideLoad) {
        loadStats();
        loadBusinesses({ silent: true });
      }
      return true;
    } catch (e) {
      const isAbort = /aborted|aborterror|signal is aborted/i.test(String(e?.message || ''));
      const unauthorized = /unauthorized|401/i.test(String(e?.message || ''));
      if (unauthorized) {
        showToast('Session expired. Please sign in again.');
        onSignOut?.(false);
        return false;
      }
      if (silent) {
        if (!isAbort) setApiError(`Live sync delayed: ${e.message}`);
        return false;
      }
      setLiveMode(false);
      setApiError(isAbort ? 'Loading... please wait' : `Loading... please wait (${e.message})`);
      setConversations([]);
      setThreads({});
      setSelectedId('');
      return false;
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const saveOwnerEmailScope = async (value) => {
    const clean = normalizeOwnerEmail(value);
    if (clean) {
      window.localStorage.setItem(OWNER_EMAIL_STORAGE_KEY, clean);
    } else {
      window.localStorage.removeItem(OWNER_EMAIL_STORAGE_KEY);
    }
    setOwnerEmail(clean);
    setSelectedBusinessId('');
    await loadBusinesses({ ownerEmailOverride: clean });
    await loadConversations({ sideLoad: false, ownerEmailOverride: clean });
    showToast(clean ? `Owner scoped to ${clean}` : 'Owner scope cleared');
  };

  const loadThread = async (conversationId, { silent = false } = {}) => {
    if (!conversationId || !liveMode) return;
    if (!silent) setThreadLoading(true);
    try {
      const data = await API.get(`/api/v2/conversation/${encodeURIComponent(conversationId)}/messages`);
      setThreads(prev => ({
        ...prev,
        [conversationId]: (data.data || []).map(normalizeMessage),
      }));
      setConversations(rows => rows.map(item => item.id === conversationId ? clearConversationUnread(item) : item));
      setApiError('');
      return true;
    } catch (e) {
      setApiError(`${e.message} Showing cached messages.`);
      return false;
    } finally {
      if (!silent) setThreadLoading(false);
    }
  };

  const sendLiveMessage = async (conversation, text, options = {}) => {
    const payload = {
      conversation_id: conversation.apiId || conversation.id,
      text,
    };
    if (options.replyToCommentId) payload.reply_to_comment_id = options.replyToCommentId;

    const result = await API.postJson('/api/v2/send-message', payload);
    const meta = result.meta || result.data || {};
    if (result.status !== 'ok') {
      throw new Error(apiErrorMessage(result, 200));
    }
    if (meta.ok === false || meta.error || meta.description) {
      throw new Error(apiErrorMessage({ meta }, 200));
    }
    return result;
  };

  const sendLiveImage = async (conversation, file, caption = '') => {
    if (!file.type.startsWith('image/')) {
      throw new Error('Please choose an image file.');
    }

    if (file.size > 10 * 1024 * 1024) {
      throw new Error('Image is too large. Maximum upload size is 10 MB.');
    }

    const fileData = await fileToDataUrl(file);
    const result = await API.postJson('/dashboard/send-image-file', {
      business_id: conversation.businessId,
      conversation_id: conversation.apiId || conversation.id,
      platform: conversation.platform,
      channel: conversation.channel || '',
      customer_id: conversation.customerId || conversation.chatId,
      chat_id: conversation.chatId || conversation.customerId,
      caption,
      file_data: fileData,
      filename: file.name || 'image.jpg',
      mime_type: file.type || 'image/jpeg',
    });

    const meta = result.meta || {};
    if (result.status !== 'ok') {
      throw new Error(apiErrorMessage(result, 200));
    }
    if (meta.ok === false || meta.error || meta.description) {
      throw new Error(apiErrorMessage({ meta }, 200));
    }

    return result;
  };

  const sendLiveVoice = async (conversation, file) => {
    if (conversation.platform === 'instagram') {
      throw new Error('Voice recording currently supports Telegram and WhatsApp. Instagram needs public media hosting first.');
    }

    if (!file.type.startsWith('audio/')) {
      throw new Error('Please choose an audio file.');
    }

    if (file.size > 10 * 1024 * 1024) {
      throw new Error('Audio is too large. Maximum upload size is 10 MB.');
    }

    const fileData = await fileToDataUrl(file);
    const result = await API.postJson('/dashboard/send-voice-file', {
      business_id: conversation.businessId,
      conversation_id: conversation.apiId || conversation.id,
      platform: conversation.platform,
      channel: conversation.channel || '',
      customer_id: conversation.customerId || conversation.chatId,
      chat_id: conversation.chatId || conversation.customerId,
      file_data: fileData,
      filename: file.name || 'voice.ogg',
      mime_type: file.type || 'audio/ogg',
    });

    const meta = result.meta || {};
    if (result.status !== 'ok') {
      throw new Error(apiErrorMessage(result, 200));
    }
    if (meta.ok === false || meta.error || meta.description) {
      throw new Error(apiErrorMessage({ meta }, 200));
    }

    return result;
  };

  const updateBusinessSetting = async (businessId, settings, persist = true) => {
    if (!businessId) {
      showToast('Select a business first');
      return;
    }
    setBusinesses(rows => rows.map(b => b.id === businessId ? { ...b, ...settings } : b));
    if (!persist || !liveMode) return;
    try {
      await API.postJson('/api/business-settings', { business_id: businessId, settings });
      showToast('Business settings saved');
      await loadBusinesses();
    } catch (e) {
      setApiError(e.message);
      showToast(e.message);
      await loadBusinesses();
    }
  };

  const sendMessage = async (text, options = {}) => {
    if (!conv) return false;

    if (!liveMode) {
      const localMessage = {
        id: `local-${Date.now()}`,
        side: 'outbound',
        type: 'text',
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        text,
      };
      setThreads(prev => ({ ...prev, [conv.id]: [...(prev[conv.id] || []), localMessage] }));
      return true;
    }

    setSending(true);
    try {
      await sendLiveMessage(conv, text, options);
      await loadThread(conv.id);
      await loadConversations();
      showToast('Message sent');
      return true;
    } catch (e) {
      setApiError(e.message);
      showToast(e.message);
      return false;
    } finally {
      setSending(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await loadConversations();
      } finally {
        if (!cancelled) setBooting(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    businessesRef.current = businesses;
  }, [businesses]);

  useEffect(() => {
    if (selectedBusinessId) loadPromptSettings(selectedBusinessId, { silent: true });
  }, [selectedBusinessId]);

  useEffect(() => {
    if (liveMode) loadOperatorAccounts(selectedBusinessId);
  }, [selectedBusinessId, liveMode]);

  useEffect(() => {
    if (liveMode) loadOperatorTasks(selectedBusinessId);
  }, [selectedBusinessId, liveMode, currentUser?.email, currentUser?.ownerEmail, currentUser?.role]);

  useEffect(() => {
    if (!selectedBusinessId || !liveMode) return;
    workspaceStateHydratedRef.current = false;
    loadWorkspaceState(selectedBusinessId);
  }, [selectedBusinessId, liveMode]);

  useEffect(() => {
    loadThread(selectedId);
  }, [selectedId, liveMode]);

  useEffect(() => {
    if (!liveMode) return undefined;

    const pollThread = async () => {
      const currentId = selectedIdRef.current;
      if (!currentId || threadPollBusy.current) return;
      threadPollBusy.current = true;
      try {
        await loadThread(currentId, { silent: true });
      } finally {
        threadPollBusy.current = false;
      }
    };

    const pollInbox = async () => {
      if (inboxPollBusy.current) return;
      inboxPollBusy.current = true;
      try {
        await loadConversations({ sideLoad: false, silent: true });
      } finally {
        inboxPollBusy.current = false;
      }
    };

    const pollStats = async () => {
      if (statsPollBusy.current) return;
      statsPollBusy.current = true;
      try {
        await loadStats();
      } finally {
        statsPollBusy.current = false;
      }
    };

    const pollTasks = async () => {
      if (tasksPollBusy.current) return;
      tasksPollBusy.current = true;
      try {
        await loadOperatorTasks(selectedBusinessId);
      } finally {
        tasksPollBusy.current = false;
      }
    };

    const syncVisible = () => {
      if (document.hidden || !liveModeRef.current) return;
      pollThread();
      pollInbox();
      pollStats();
      pollTasks();
    };

    const threadTimer = window.setInterval(() => {
      if (!document.hidden) pollThread();
    }, THREAD_POLL_MS);
    const inboxTimer = window.setInterval(() => {
      if (!document.hidden) pollInbox();
    }, INBOX_POLL_MS);
    const statsTimer = window.setInterval(() => {
      if (!document.hidden) pollStats();
    }, STATS_POLL_MS);
    const tasksTimer = window.setInterval(() => {
      if (!document.hidden) pollTasks();
    }, TASKS_POLL_MS);

    document.addEventListener('visibilitychange', syncVisible);
    syncVisible();

    return () => {
      window.clearInterval(threadTimer);
      window.clearInterval(inboxTimer);
      window.clearInterval(statsTimer);
      window.clearInterval(tasksTimer);
      document.removeEventListener('visibilitychange', syncVisible);
    };
  }, [liveMode, selectedBusinessId]);

  const toggleAi = async () => {
    if (!conv) return;
    const nextEnabled = !conv.aiOn;
    rememberAiOverride(selectedId, nextEnabled);
    setConversations(cs => cs.map(c => c.id === selectedId ? { ...c, aiOn: nextEnabled, needsHuman: nextEnabled ? false : c.needsHuman } : c));
    setMoreOpen(false);
    if (!liveMode) {
      showToast(nextEnabled ? 'AI replies enabled locally' : 'AI replies paused locally');
      return;
    }
    try {
      await API.postJson(`/api/v2/conversation/${encodeURIComponent(conv.apiId || conv.id)}/ai-toggle`, {
        enabled: nextEnabled,
      });
      showToast(nextEnabled ? 'AI replies enabled' : 'AI replies paused');
    } catch (e) {
      rememberAiOverride(selectedId, !nextEnabled);
      setConversations(cs => cs.map(c => c.id === selectedId ? { ...c, aiOn: !nextEnabled } : c));
      setApiError(e.message);
      showToast(e.message);
    }
  };

  const pinConversation = () => {
    if (!conv) return;
    const nextPinned = !conv.pinned;
    setConversations(cs => cs.map(c => c.id === selectedId ? {
      ...c,
      pinned: nextPinned,
      tags: nextPinned ? Array.from(new Set(['Pinned', ...(c.tags || [])])) : (c.tags || []).filter(tag => tag !== 'Pinned'),
    } : c));
    setMoreOpen(false);
    showToast(nextPinned ? 'Conversation pinned' : 'Conversation unpinned');
  };

  const archiveConversation = () => {
    if (!conv) return;
    const archivedId = conv.id;
    setConversations(cs => {
      const next = cs.filter(c => c.id !== archivedId);
      setSelectedId(next[0]?.id || '');
      return next;
    });
    setMoreOpen(false);
    showToast('Conversation archived locally');
  };

  const deleteConversation = async () => {
    if (!conv) return;
    const target = conv;
    setMoreOpen(false);

    if (!window.confirm('Delete this chat from the dashboard database? This will not delete it from Instagram, Telegram, or WhatsApp.')) {
      return;
    }

    if (!liveMode) {
      rememberDeletedConversation(target.id);
      removeConversationFromUi(target.id);
      showToast('Chat deleted locally');
      return;
    }

    try {
      await API.delete(`/api/v2/conversation/${encodeURIComponent(target.apiId || target.id)}`);
      rememberDeletedConversation(target.id);
      removeConversationFromUi(target.id);
      showToast('Chat deleted from dashboard');
    } catch (e) {
      if (String(e.message || '').includes('405')) {
        rememberDeletedConversation(target.id);
        removeConversationFromUi(target.id);
        setApiError('');
        showToast('Backend delete is not deployed yet, so this chat is hidden locally');
        return;
      }
      setApiError(e.message);
      showToast(e.message);
    }
  };

  const handleTool = async (tool, setDraft, file, caption = '') => {
    if (file) {
      if (!conv) return false;
      if (!liveMode) {
        showToast(`Connect live backend before sending ${tool === 'voice' ? 'voice notes' : 'images'}`);
        return false;
      }

      setSending(true);
      try {
        if (tool === 'voice') {
          await sendLiveVoice(conv, file);
        } else {
          await sendLiveImage(conv, file, caption.trim());
        }
        await loadThread(conv.id);
        await loadConversations({ silent: true, sideLoad: false });
        showToast(tool === 'voice' ? 'Voice note sent' : 'Image sent');
        return true;
      } catch (e) {
        setApiError(e.message);
        showToast(e.message);
        return false;
      } finally {
        setSending(false);
      }
    }

    if (tool === 'voice-unsupported') {
      showToast('Voice recording is not supported in this browser');
      return false;
    }

    if (tool === 'voice-instagram') {
      showToast('Voice recording currently supports Telegram and WhatsApp. Instagram needs public media hosting first.');
      return false;
    }

    if (tool === 'voice-permission') {
      showToast(caption || 'Microphone permission was denied');
      return false;
    }

    if (tool === 'voice') {
      showToast('Press the mic to start recording');
      return false;
    }

    showToast('Choose an image to send');
    return false;
  };

  const changeView = (view) => {
    if (isOperator && !['leads', 'inbox', 'operators', 'settings', 'profile'].includes(view)) {
      setActiveView('leads');
      showToast('Operator access is limited to Leads, Inbox, Operators, Settings, and Profile');
      return;
    }
    if ((view === 'operators' || view === 'settings') && liveModeRef.current) {
      loadOperatorAccounts(selectedBusinessId);
    }
    setActiveView(view);
    const names = {
      inbox: t.inbox,
      insights: t.insights,
      leads: t.leads || 'Leads',
      clients: t.clients || 'Clients',
      operators: t.operators || 'Operators',
      knowledge: t.knowledge,
      prompts: 'AI Prompt Settings',
      accounts: t.accounts,
      settings: t.settings,
      profile: 'Profile',
    };
    showToast(`${names[view] || view} selected`);
  };

  const setLeadStage = (conversationId, stage) => {
    if (!LEAD_STAGE_ORDER.includes(stage)) return;
    setLeadStages(prev => {
      const next = { ...prev, [conversationId]: stage };
      writeStoredObject(LEAD_STAGES_STORAGE_KEY, next);
      queueWorkspaceStateSave({ lead_stages: next });
      return next;
    });
    showToast(`Lead stage updated to ${stage}`);
  };

  const setLeadPrice = (conversationId, price) => {
    setLeadPrices(prev => {
      const next = { ...prev };
      const clean = String(price || '').trim();
      if (clean) next[conversationId] = price;
      else delete next[conversationId];
      writeStoredObject(LEAD_PRICES_STORAGE_KEY, next);
      queueWorkspaceStateSave({ lead_prices: next });
      return next;
    });
  };

  const setOperatorDealCount = (operatorId, value) => {
    setOperatorDeals(prev => {
      const next = { ...prev, [operatorId]: Math.max(0, Number(value || 0)) };
      writeStoredObject(OPERATOR_DEALS_STORAGE_KEY, next);
      queueWorkspaceStateSave({ operator_deals: next });
      return next;
    });
  };

  const addOperatorAdminNote = async (text, recipients = ['*'], mode = 'all') => {
    const clean = String(text || '').trim();
    if (!clean) return;
    if (!selectedBusinessId) {
      showToast('Select a business first');
      return;
    }

    if (!liveMode) {
      setOperatorAdminNotes(prev => {
        const next = [{
          id: `${Date.now()}`,
          text: clean,
          recipients,
          mode,
          createdAt: new Date().toISOString(),
        }, ...prev].slice(0, 50);
        writeStoredObject(OPERATOR_ADMIN_NOTES_STORAGE_KEY, { items: next });
        queueWorkspaceStateSave({ operator_admin_notes: { items: next } });
        return next;
      });
      showToast('Task saved locally. Connect live backend to sync with operators.');
      return;
    }

    try {
      await API.postJson('/api/v2/operator-tasks', {
        business_id: selectedBusinessId,
        text: clean,
        recipients: Array.isArray(recipients) ? recipients : ['*'],
        assign_mode: String(mode || 'all'),
      });
      await loadOperatorTasks(selectedBusinessId);
      showToast('Task sent to operators');
    } catch (e) {
      setApiError(e.message);
      showToast(e.message);
    }
  };

  const selectConversation = (conversationId) => {
    setSelectedId(conversationId);
    setActiveView('inbox');
    setMoreOpen(false);
  };

  // Mark selected unread as read
  useEffect(() => {
    if (!selectedId) return;
    setConversations(cs => cs.map(c => c.id === selectedId ? clearConversationUnread(c) : c));
  }, [selectedId, liveMode]);

  if (booting) {
    return (
      <main className="app-loading-screen" role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <p>Loading... please wait</p>
      </main>
    );
  }

  return (
    <>
      <div className={`app ${activeView === 'inbox' ? '' : 'workspace-mode'}`}>
        <TopBar
          t={t}
          lang={lang}
          setLang={setLang}
          theme={theme}
          setTheme={setTheme}
          conv={conv}
          aiOn={aiOn}
          activeView={activeView}
          onToggleAi={toggleAi}
          onRefresh={refreshWorkspace}
          onToast={showToast}
          onPin={pinConversation}
          onArchive={archiveConversation}
          onDelete={deleteConversation}
          onMore={() => setMoreOpen(v => !v)}
          moreOpen={moreOpen}
          onOpenProfile={() => setActiveView('profile')}
          onSignOut={onSignOut}
          userProfile={userProfile}
          onUpdateUserProfile={updateUserProfile}
        />
        <Rail t={t} activeView={activeView} onView={changeView} currentUser={currentUser} userProfile={userProfile} />
        <ListColumn
          conversations={conversations}
          selectedId={selectedId}
          onSelect={selectConversation}
          t={t}
          loading={loading}
          apiError={apiError}
          liveMode={liveMode}
          onRefresh={refreshWorkspace}
        />
        {activeView === 'inbox' ? (
          <ThreadColumn
            conv={conv}
            aiOn={aiOn}
            onToggleAi={toggleAi}
            t={t}
            messages={messages}
            onSend={sendMessage}
            sending={sending}
            threadLoading={threadLoading}
            onTool={handleTool}
          />
        ) : (
          <WorkspacePanel
            lang={lang}
            t={t}
            view={activeView}
            stats={stats}
            conversations={conversations}
            businesses={businesses}
            selectedBusinessId={selectedBusinessId}
            onSelectBusiness={setSelectedBusinessId}
            onRefresh={refreshWorkspace}
            onBusinessSetting={updateBusinessSetting}
            promptSettings={promptSettings}
            onPromptSetting={updatePromptSetting}
            onSavePromptSettings={savePromptSettings}
            promptLoading={promptLoading}
            promptSaving={promptSaving}
            onToast={showToast}
            onGeneratePrompt={generatePromptSuggestion}
            generatorState={promptGeneratorState}
            leadStages={leadStages}
            leadPrices={leadPrices}
            operatorDeals={operatorDeals}
            adminNotes={operatorAdminNotes}
            operatorAccounts={operatorAccounts}
            onReloadOperatorAccounts={() => loadOperatorAccounts(selectedBusinessId)}
            onLeadStageChange={setLeadStage}
            onLeadPriceChange={setLeadPrice}
            onOperatorDealChange={setOperatorDealCount}
            onAdminNote={addOperatorAdminNote}
            onOpenConversation={selectConversation}
            ownerEmail={ownerEmail}
            onOwnerEmailSave={saveOwnerEmailScope}
            onSignOut={onSignOut}
            currentUser={currentUser}
            userProfile={userProfile}
            onUpdateUserProfile={updateUserProfile}
          />
        )}
        {activeView === 'inbox' && <DetailColumn conv={conv} t={t} stats={stats} onDelete={deleteConversation} messages={messages} />}
      </div>
      <Toast message={toast} />

      <window.TweaksPanel title="Tweaks">
        <window.TweakSection label="Appearance">
          <window.TweakRadio
            label="Theme"
            value={theme}
            options={[{ label: 'Light', value: 'light' }, { label: 'Dark', value: 'dark' }]}
            onChange={(v) => {
              setTheme(v);
              window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { theme: v } }, '*');
            }}
          />
        </window.TweakSection>
        <window.TweakSection label="Language">
          <window.TweakRadio
            label="UI"
            value={lang}
            options={[{ label: 'EN', value: 'en' }, { label: 'UZ', value: 'uz' }, { label: 'RU', value: 'ru' }]}
            onChange={setLang}
          />
        </window.TweakSection>
      </window.TweaksPanel>
    </>
  );
}

function Root() {
  const [lang, setLang] = useState(() => window.localStorage.getItem(UI_LANG_STORAGE_KEY) || 'en');
  const [showDashboard, setShowDashboard] = useState(() => window.location.hash === DASHBOARD_HASH || urlParams.get('dashboard') === '1');
  const [currentUser, setCurrentUser] = useState(() => readAuthSession() || null);
  const [signedIn, setSignedIn] = useState(() => !!readAuthSession()?.token);

  useEffect(() => {
    window.localStorage.setItem(UI_LANG_STORAGE_KEY, lang);
  }, [lang]);

  useEffect(() => {
    const onHashChange = () => setShowDashboard(window.location.hash === DASHBOARD_HASH);
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const openDashboard = () => {
    window.location.hash = DASHBOARD_HASH;
    setShowDashboard(true);
  };

  const backToLanding = () => {
    window.location.hash = '';
    setShowDashboard(false);
  };

  const signOut = (backToHome = true) => {
    clearAuthSession();
    setCurrentUser(null);
    setSignedIn(false);
    if (backToHome) backToLanding();
    else {
      window.location.hash = DASHBOARD_HASH;
      setShowDashboard(true);
    }
  };

  if (!showDashboard) return <LandingPage onOpenDashboard={openDashboard} lang={lang} setLang={setLang} />;
  if (!signedIn) return <SignInPage lang={lang} onSignedIn={(session) => { setCurrentUser(session || readAuthSession()); setSignedIn(true); }} onBack={backToLanding} />;
  return <App lang={lang} setLang={setLang} onSignOut={signOut} currentUser={currentUser || readAuthSession()} />;
}

createRoot(document.getElementById('root')).render(<Root />);
