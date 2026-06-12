/* global window */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { createRoot } from 'react-dom/client';
import { I } from './icons.jsx';

import './app.css';
import './tweaks-panel.jsx';
import './data.jsx';
const IS_LOCALHOST = ['localhost', '127.0.0.1'].includes(window.location.hostname);

const ENV_API_BASE = import.meta.env.VITE_API_URL || 'https://agent-1-xi6h.onrender.com';
const ENV_DASHBOARD_SECRET = import.meta.env.VITE_DASHBOARD_SECRET || '';

const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('clear_auth')) {
  window.localStorage.removeItem('instaagent_dashboard_secret');
  window.sessionStorage.removeItem('instaagent_dashboard_secret');
  window.localStorage.removeItem('instaagent_dashboard_auth');
  window.localStorage.removeItem('instaagent_owner_email');
  window.localStorage.removeItem('instaagent_api_base');
}
function sanitizeApiBase(rawValue) {
  const value = String(rawValue || '').trim().replace(/\/$/, '');
  if (!value) return '';
  if (/^https?:\/\//i.test(value)) {
    // Prevent mixed-content fetch errors when dashboard is opened on HTTPS.
    if (window.location.protocol === 'https:' && /^http:\/\//i.test(value)) {
      return '';
    }
    return value;
  }
  return '';
}

const RAW_API_BASE = (
  urlParams.get('api') ||
  window.localStorage.getItem('instaagent_api_base') ||
  ENV_API_BASE ||
  window.INSTAAGENT_API_BASE ||
  (IS_LOCALHOST ? 'http://localhost:8000' : '')
);
let API_BASE = sanitizeApiBase(RAW_API_BASE);
if (!API_BASE) {
  API_BASE = sanitizeApiBase(ENV_API_BASE) || sanitizeApiBase(window.INSTAAGENT_API_BASE) || '';
}

const DASHBOARD_SECRET =
  urlParams.get('secret') ||
  (IS_LOCALHOST ? 'localdev' : '') ||
  ENV_DASHBOARD_SECRET ||
  window.sessionStorage.getItem('instaagent_dashboard_secret') ||
  window.localStorage.getItem('instaagent_dashboard_secret') ||
  window.INSTAAGENT_DASHBOARD_SECRET ||
  '';

if (urlParams.get('api') && API_BASE) window.localStorage.setItem('instaagent_api_base', API_BASE);
if (!API_BASE) window.localStorage.removeItem('instaagent_api_base');
if (urlParams.get('secret') && DASHBOARD_SECRET !== 'YOUR_DASHBOARD_SECRET') {
  window.sessionStorage.setItem('instaagent_dashboard_secret', DASHBOARD_SECRET);
}
if (window.localStorage.getItem('instaagent_dashboard_secret') === 'YOUR_DASHBOARD_SECRET') {
  window.localStorage.removeItem('instaagent_dashboard_secret');
}
if (window.sessionStorage.getItem('instaagent_dashboard_secret') === 'YOUR_DASHBOARD_SECRET') {
  window.sessionStorage.removeItem('instaagent_dashboard_secret');
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
    const token = String(parsed.token || '').trim();
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

function clearAuthSession() {
  window.localStorage.removeItem(DASHBOARD_AUTH_STORAGE_KEY);
  window.localStorage.removeItem(OWNER_EMAIL_STORAGE_KEY);
  window.localStorage.removeItem('instaagent_dashboard_secret');
  window.sessionStorage.removeItem('instaagent_dashboard_secret');
}

function localDevDashboardSession() {
  if (dashboardSecret() !== 'localdev') return null;
  const ownerEmail = ownerEmailFromUrl() || ownerEmailFromStorage() || 'milanapremium2025@gmail.com';
  return {
    ownerEmail: normalizeOwnerEmail(ownerEmail),
    token: 'localdev-demo-token',
    isAdmin: true,
    role: 'super_admin',
    at: new Date().toISOString(),
  };
}

function isLocalDevDashboardMode() {
  return dashboardSecret() === 'localdev';
}

function resolveRoleScope(currentUser = {}, businesses = []) {
  const rawRole = String(currentUser?.role || '').trim().toLowerCase();
  const adminRoles = new Set(['owner', 'admin', 'super_admin']);
  if (adminRoles.has(rawRole)) return { role: rawRole, isOperator: false };
  if (rawRole === 'operator') return { role: 'operator', isOperator: true };
  if (currentUser?.isAdmin === true) return { role: 'admin', isOperator: false };

  const email = normalizeOwnerEmail(currentUser?.ownerEmail || currentUser?.email || '');
  if (email) {
    const ownsBusiness = (businesses || []).some((row) => normalizeOwnerEmail(row?.owner_email || '') === email);
    if (ownsBusiness) return { role: 'owner', isOperator: false };
  }
  return { role: rawRole || 'operator', isOperator: true };
}

function scopedPath(path) {
  const ownerEmail = resolvedOwnerEmail();
  if (!ownerEmail) return path;
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}${OWNER_EMAIL_PARAM}=${encodeURIComponent(ownerEmail)}`;
}

const API = {
  isAbortError(err) {
    const message = String(err?.message || err || '').toLowerCase();
    return message.includes('aborted') || message.includes('aborterror') || message.includes('signal is aborted');
  },
  async fetchWithTimeout(url, options = {}, timeoutMs = 35000) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } catch (err) {
      if (API.isAbortError(err)) {
        throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s. Please retry.`);
      }
      throw err;
    } finally {
      window.clearTimeout(timer);
    }
  },
  async get(path, { timeoutMs = 35000 } = {}) {
    const res = await API.fetchWithTimeout(`${API_BASE}${scopedPath(path)}`, { headers: apiHeaders() }, timeoutMs);
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
  async post(path, params = {}, { timeoutMs = 35000 } = {}) {
    const qs = new URLSearchParams(params);
    const endpoint = `${scopedPath(path)}${qs.toString() ? `${scopedPath(path).includes('?') ? '&' : '?'}${qs.toString()}` : ''}`;
    const res = await API.fetchWithTimeout(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: apiHeaders(),
    }, timeoutMs);
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
  async postJson(path, body = {}, { timeoutMs = 35000 } = {}) {
    const res = await API.fetchWithTimeout(`${API_BASE}${scopedPath(path)}`, {
      method: 'POST',
      headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, owner_email: body?.owner_email || resolvedOwnerEmail() || undefined }),
    }, timeoutMs);
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
  async delete(path, { timeoutMs = 35000 } = {}) {
    const res = await API.fetchWithTimeout(`${API_BASE}${scopedPath(path)}`, {
      method: 'DELETE',
      headers: apiHeaders(),
    }, timeoutMs);
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
};

const THREAD_POLL_MS = 1200;
const INBOX_POLL_MS = 2000;
const STATS_POLL_MS = 20000;
const THREAD_WARMUP_CONCURRENCY = 6;
const AI_OVERRIDE_STORAGE_KEY = 'instaagent_ai_overrides';
const DELETED_CONVERSATIONS_STORAGE_KEY = 'instaagent_deleted_conversations';
const LEAD_STAGES_STORAGE_KEY = 'instaagent_lead_stages';
const LEAD_PRICES_STORAGE_KEY = 'instaagent_lead_prices';
const CLIENT_OWNERS_STORAGE_KEY = 'instaagent_client_owners';
const MANUAL_CLIENTS_STORAGE_KEY = 'instaagent_manual_clients';
const MANUAL_LEADS_STORAGE_KEY = 'instaagent_manual_leads';
const OPERATOR_DEALS_STORAGE_KEY = 'instaagent_operator_deals';
const OPERATOR_ADMIN_NOTES_STORAGE_KEY = 'instaagent_operator_admin_notes';
const USER_PROFILE_STORAGE_KEY = 'instaagent_user_profiles';
const CACHED_CONVERSATIONS_STORAGE_KEY = 'instaagent_cached_conversations_v1';
const CACHED_THREADS_STORAGE_KEY = 'instaagent_cached_threads_v1';
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

function loadCachedConversations() {
  const payload = readStoredObject(CACHED_CONVERSATIONS_STORAGE_KEY);
  const items = Array.isArray(payload.items) ? payload.items : [];
  const selectedId = String(payload.selectedId || '');
  return { items, selectedId };
}

function loadCachedThreads() {
  const payload = readStoredObject(CACHED_THREADS_STORAGE_KEY);
  const items = payload.items && typeof payload.items === 'object' ? payload.items : {};
  return items;
}

function trimThreadCache(items = {}) {
  const entries = Object.entries(items || {});
  if (!entries.length) return {};
  const sorted = entries.sort((a, b) => Number(b[1]?.updatedAt || 0) - Number(a[1]?.updatedAt || 0));
  const next = {};
  sorted.slice(0, 120).forEach(([id, row]) => {
    const messages = Array.isArray(row?.messages) ? row.messages.slice(-80) : [];
    next[id] = {
      updatedAt: Number(row?.updatedAt || Date.now()),
      messages,
    };
  });
  return next;
}

function getThreadMessages(entry) {
  if (!entry) return [];
  if (Array.isArray(entry)) return entry;
  if (Array.isArray(entry.messages)) return entry.messages;
  return [];
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
  if (/human agent/i.test(String(description || '')) && /review/i.test(String(description || ''))) {
    return 'Instagram Human Agent is not approved for this Meta app. Ask the customer to send a new DM first.';
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
  const savedSecret = dashboardSecret();
  if (savedSecret && savedSecret !== 'YOUR_DASHBOARD_SECRET') headers['x-dashboard-secret'] = savedSecret;
  const auth = readAuthSession();
  if (auth?.token) headers.Authorization = `Bearer ${auth.token}`;
  const ownerEmail = resolvedOwnerEmail();
  if (ownerEmail) headers['x-owner-email'] = ownerEmail;
  return headers;
}

function dashboardSecret() {
  const savedSecret =
    window.sessionStorage.getItem('instaagent_dashboard_secret') ||
    window.localStorage.getItem('instaagent_dashboard_secret') ||
    DASHBOARD_SECRET;
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

function mediaUrlWithSecret(path) {
  const clean = String(path || '').trim();
  if (!clean) return '';
  const qs = new URLSearchParams();
  const secret = dashboardSecret();
  if (secret) qs.set('token', secret);
  return `${API_BASE}${clean}${qs.toString() ? `?${qs.toString()}` : ''}`;
}

function telegramBotMediaUrl(row) {
  const fileId = String(row.media_file_id || row.mediaFileId || '').trim();
  if (!fileId || String(row.platform || '').toLowerCase() !== 'telegram') return '';
  return mediaUrlWithSecret(`/api/telegram-bot-media/${encodeURIComponent(fileId)}`);
}

function whatsappMediaUrl(row) {
  const mediaId = getWhatsAppMediaId(row);
  if (!mediaId || String(row.platform || '').toLowerCase() !== 'whatsapp') return '';
  return mediaUrlWithSecret(`/api/whatsapp/media/${encodeURIComponent(mediaId)}`);
}

function resolveMediaUrl(row = {}) {
  const direct = row.media_url || row.mediaUrl;
  if (direct) return withMediaToken(direct);
  return telegramUserMediaUrl(row) || telegramBotMediaUrl(row) || whatsappMediaUrl(row);
}

function withMediaToken(url) {
  if (!url) return '';
  const secret = dashboardSecret();
  const needsToken = [
    '/api/whatsapp/media/',
    '/api/telegram-user-media/',
    '/api/telegram-bot-media/',
  ].some(path => String(url).includes(path));
  if (!secret || !needsToken) return url;

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

function waitForVideoEvent(video, eventName) {
  return new Promise((resolve, reject) => {
    const onEvent = () => {
      cleanup();
      resolve();
    };
    const onError = () => {
      cleanup();
      reject(new Error('Could not read video metadata'));
    };
    const cleanup = () => {
      video.removeEventListener(eventName, onEvent);
      video.removeEventListener('error', onError);
    };
    video.addEventListener(eventName, onEvent, { once: true });
    video.addEventListener('error', onError, { once: true });
  });
}

async function captureVideoFramesFromFile(file, frameCount = 4) {
  if (!file || !file.type?.startsWith('video/')) return { frames: [], duration: 0 };
  const url = URL.createObjectURL(file);
  const video = document.createElement('video');
  video.src = url;
  video.muted = true;
  video.playsInline = true;
  video.preload = 'metadata';

  try {
    await waitForVideoEvent(video, 'loadedmetadata');
    const duration = Number.isFinite(video.duration) ? video.duration : 0;
    const canvas = document.createElement('canvas');
    const width = Math.min(720, video.videoWidth || 720);
    const height = Math.round(width * ((video.videoHeight || 1280) / (video.videoWidth || 720)));
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    const frames = [];
    const usableDuration = Math.max(0.1, duration || 1);
    const count = Math.max(1, Math.min(frameCount, 4));

    for (let index = 0; index < count; index += 1) {
      const time = Math.min(usableDuration - 0.05, usableDuration * ((index + 1) / (count + 1)));
      video.currentTime = Math.max(0, time);
      await waitForVideoEvent(video, 'seeked');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      frames.push(canvas.toDataURL('image/jpeg', 0.74));
    }
    return { frames, duration: Math.round(duration || 0) };
  } finally {
    URL.revokeObjectURL(url);
  }
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
  const [secret, setSecret] = useState(dashboardSecret());
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
      setError('Access key is required.');
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
      window.localStorage.removeItem('instaagent_dashboard_secret');
      window.sessionStorage.removeItem('instaagent_dashboard_secret');
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
      window.localStorage.removeItem('instaagent_dashboard_secret');
      window.sessionStorage.removeItem('instaagent_dashboard_secret');
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
  if (resolveMediaUrl(row)) return `${media} · open media`;
  if (source) return `${media} · id ${String(source).slice(0, 10)}...`;
  return `${media} · no preview`;
}

function normalizeConversation(row) {
  const parts = String(row.id || '').split('::');
  const parsedPlatform = parts[0] || '';
  const parsedBusinessId = parts[1] || '';
  const parsedChannel = parts[2] || '';
  const parsedCustomerId = parts[3] || '';
  const platform = row.platform || 'instagram';
  const customerId = row.customer_id || parsedCustomerId;
  const chatId = row.chat_id || customerId;
  const rawName = String(row.customer_name || row.name || '').trim();
  const generatedInstagramName = /^instagram\s+(user|client|ig user)\s+\d{2,}$/i.test(rawName);
  const numericName = /^\d{6,}$/.test(rawName);
  const name = rawName && !generatedInstagramName && !numericName
    ? rawName
    : (platform === 'instagram' && customerId ? `@${customerId}` : `Client ${String(customerId || '').slice(-4)}`);
  const unread = Number(row.unread_count ?? row.unread ?? 0);
  const total = Number(row.total_messages ?? row.kpis?.orders ?? 0);
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
    mediaUrl: resolveMediaUrl(row),
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

const LOCAL_OUTBOUND_TTL_MS = 5 * 60 * 1000;

function mergeLocalOutboundMessages(serverMessages = [], currentMessages = [], rememberedMessages = []) {
  const localById = new Map();
  for (const message of [...(currentMessages || []), ...(rememberedMessages || [])]) {
    if (!message?.id) continue;
    localById.set(String(message.id), message);
  }
  const localOutbound = Array.from(localById.values()).filter(message => (
    message?.side === 'outbound' &&
    (message.local || message.pending || message.failed || String(message.id || '').startsWith('optimistic-'))
  ));
  const usedLocal = new Set();

  const merged = serverMessages.map(serverMessage => {
    if (serverMessage.side !== 'outbound') return serverMessage;
    const serverText = String(serverMessage.text || '').trim();
    const localIndex = localOutbound.findIndex((message, index) => (
      !usedLocal.has(index) &&
      serverText &&
      String(message.text || '').trim() === serverText
    ));
    if (localIndex < 0) return serverMessage;

    usedLocal.add(localIndex);
    const localMessage = localOutbound[localIndex];
    return {
      ...serverMessage,
      ...localMessage,
      day: serverMessage.day || localMessage.day,
      time: localMessage.time || serverMessage.time,
      raw: serverMessage.raw,
      serverId: serverMessage.id,
      pending: false,
      failed: false,
      error: '',
    };
  });

  for (let index = 0; index < localOutbound.length; index += 1) {
    if (!usedLocal.has(index)) {
      merged.push(localOutbound[index]);
    }
  }

  return merged;
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
    products: 'Products', prices: 'Prices', delivery: 'Delivery', faq: 'FAQ', contacts: 'Contacts', catalogLinks: 'Catalog links', telegram_bag: 'Qop size rule',
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
    client: 'Client', lastMessage: 'Last message', status: 'Status', channel: 'Channel', ownerAssigned: 'Owner', pickClient: 'Pick me', unpickClient: 'Unpick',
    manualLeadName: 'Lead name', manualLeadSource: 'Source', manualLeadOwner: 'Operator', manualLeadNote: 'Note', addManualLead: 'Add manual lead',
    operatorsTitle: 'Operators panel', operatorsSubtitle: 'Operator workspace for tasks, client messages, and leads.',
    textToOperators: 'Text to operators', textToOperatorsPlaceholder: 'Write task for operators...', saveAdminNote: 'Send task',
    adminNotes: 'Tasks history', noAdminNotes: 'No tasks yet.', messagesFromClients: 'Messages from clients',
    tasksFromAdmin: 'Tasks from admin', noTasksForYou: 'No tasks assigned to you.',
    assignOne: 'Assign one', assignGroup: 'Assign group', assignAll: 'All operators',
    operatorRanking: 'Operators ranking', successfulDeals: 'Successful deals', downloadOperatorReport: 'Download PDF', operatorPanel: 'Operator panel', adminPanel: 'Admin panel',
    operatorAccounts: 'Operator accounts', operatorAccountsHint: 'Create operator logins for this business.', operatorId: 'Operator ID', operatorPassword: 'Password',
    addOperator: 'Add operator', noOperators: 'No operators yet.',
    igGrowthTitle: 'Instagram Growth Analyzer',
    igGrowthSubtitle: 'AI recommendations for content quality, engagement, and conversion.',
    igGrowthScore: 'Account score',
    igGrowthProduct: 'Product to promote this week',
    igGrowthProblems: 'Main problems',
    igGrowthNextContent: 'Recommended next content',
    igGrowthWeeklyPlan: 'Weekly content plan',
    igGrowthMonthlyPlan: 'Monthly focus',
    igGrowthTasks: 'Account improvement tasks',
    igGrowthQuestions: 'Common customer questions',
    igGrowthScope: 'Analysis scope',
    igGrowthLoading: 'Analyzing Instagram activity...',
    igGrowthEmpty: 'No analysis yet. Connect live data and refresh.',
    igGrowthRefresh: 'Refresh analysis',
    igGrowthRetry: 'Retry',
    postsTitle: 'Posts',
    postsSubtitle: 'Import Instagram posts/reels and add post-specific info for bot replies.',
    importPosts: 'Import posts',
    refreshPosts: 'Refresh posts',
    postsLoading: 'Loading posts...',
    postsEmpty: 'No posts imported yet.',
    postExtraInfo: 'Post extra info for bot replies',
    savePostInfo: 'Save post info',
    postSaved: 'Post info saved',
    videoAnalyzerTitle: 'Video Analyzer',
    videoAnalyzerSubtitle: 'Analyze Reels, TikToks, and Shorts with Gemini.',
    videoAnalyzerUpload: 'Upload Reel, TikTok, or Shorts',
    videoAnalyzerNiche: 'Niche',
    videoAnalyzerDescription: 'Current caption',
    videoAnalyzerDetails: 'Video details',
    videoAnalyzerRun: 'Analyze',
    videoAnalyzerLoading: 'Analyzing...',
    videoAnalyzerPreview: 'Video preview',
    videoAnalyzerReport: 'AI report',
    videoAnalyzerMeta: 'Gemini analysis',
    videoAnalyzerEmpty: 'Upload a video or add text details, then run analysis.',
    copy: 'Copy',
    copied: 'Copied',
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
    products: 'Mahsulotlar', prices: 'Narxlar', delivery: 'Yetkazib berish', faq: 'FAQ', contacts: 'Kontaktlar', catalogLinks: 'Katalog linklari', telegram_bag: 'Qop razmer qoidasi',
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
    client: 'Mijoz', lastMessage: 'Oxirgi xabar', status: 'Status', channel: 'Kanal', ownerAssigned: 'Egası', pickClient: 'O‘zim olish', unpickClient: 'Bo‘shatish',
    manualLeadName: 'Lead ismi', manualLeadSource: 'Manba', manualLeadOwner: 'Operator', manualLeadNote: 'Izoh', addManualLead: 'Manual lead qo‘shish',
    operatorsTitle: 'Operator paneli', operatorsSubtitle: 'Vazifalar, mijoz xabarlari va lidlar uchun operator ish maydoni.',
    textToOperators: 'Operatorlarga topshiriq', textToOperatorsPlaceholder: 'Operatorlar uchun vazifa yozing...', saveAdminNote: 'Vazifani yuborish',
    adminNotes: 'Vazifalar tarixi', noAdminNotes: 'Hali vazifa yo‘q.', messagesFromClients: 'Mijozlardan xabarlar',
    tasksFromAdmin: 'Admindan vazifalar', noTasksForYou: 'Sizga tayinlangan vazifa yo‘q.',
    assignOne: 'Bitta operator', assignGroup: 'Guruhga', assignAll: 'Barcha operatorlar',
    operatorRanking: 'Operatorlar reytingi', successfulDeals: 'Muvaffaqiyatli bitimlar', downloadOperatorReport: 'PDF yuklab olish', operatorPanel: 'Operator panel', adminPanel: 'Admin panel',
    operatorAccounts: 'Operator akkauntlari', operatorAccountsHint: 'Bu biznes uchun operator loginlarini yarating.', operatorId: 'Operator ID', operatorPassword: 'Parol',
    addOperator: 'Operator qo‘shish', noOperators: 'Hali operator yo‘q.',
    igGrowthTitle: 'Instagram Growth Analyzer',
    igGrowthSubtitle: 'Kontent sifati, engagement va konversiya bo‘yicha AI tavsiyalar.',
    igGrowthScore: 'Akkaunt skori',
    igGrowthProduct: 'Bu hafta targ‘ib qilinadigan mahsulot',
    igGrowthProblems: 'Asosiy muammolar',
    igGrowthNextContent: 'Keyingi tavsiya etilgan kontent',
    igGrowthWeeklyPlan: 'Haftalik kontent reja',
    igGrowthMonthlyPlan: 'Oylik fokus',
    igGrowthTasks: 'Akkauntni yaxshilash vazifalari',
    igGrowthQuestions: 'Mijozlarning ko‘p beradigan savollari',
    igGrowthScope: 'Tahlil qamrovi',
    igGrowthLoading: 'Instagram faolligi tahlil qilinmoqda...',
    igGrowthEmpty: 'Hali tahlil yo‘q. Live data ulang va yangilang.',
    igGrowthRefresh: 'Tahlilni yangilash',
    igGrowthRetry: 'Qayta urinish',
    postsTitle: 'Postlar',
    postsSubtitle: 'Instagram post/reellarni import qiling va bot javobi uchun postga xos maʼlumot yozing.',
    importPosts: 'Postlarni import qilish',
    refreshPosts: 'Postlarni yangilash',
    postsLoading: 'Postlar yuklanmoqda...',
    postsEmpty: 'Hali post import qilinmagan.',
    postExtraInfo: 'Bot javobi uchun postga xos qo‘shimcha maʼlumot',
    savePostInfo: 'Post maʼlumotini saqlash',
    postSaved: 'Post maʼlumoti saqlandi',
    videoAnalyzerTitle: 'Video Analyzer',
    videoAnalyzerSubtitle: 'Reels, TikTok va Shorts videolarini Gemini bilan tahlil qiling.',
    videoAnalyzerUpload: 'Reel, TikTok yoki Shorts yuklash',
    videoAnalyzerNiche: 'Nisha',
    videoAnalyzerDescription: 'Hozirgi caption',
    videoAnalyzerDetails: 'Video detallari',
    videoAnalyzerRun: 'Tahlil qilish',
    videoAnalyzerLoading: 'Tahlil qilinmoqda...',
    videoAnalyzerPreview: 'Video preview',
    videoAnalyzerReport: 'AI hisobot',
    videoAnalyzerMeta: 'Gemini tahlili',
    videoAnalyzerEmpty: 'Video yuklang yoki matnli detallar qo‘shing, keyin tahlilni boshlang.',
    copy: 'Copy',
    copied: 'Copied',
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
    products: 'Товары', prices: 'Цены', delivery: 'Доставка', faq: 'FAQ', contacts: 'Контакты', catalogLinks: 'Ссылки каталога', telegram_bag: 'Правило размеров мешка',
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
    client: 'Клиент', lastMessage: 'Последнее сообщение', status: 'Статус', channel: 'Канал', ownerAssigned: 'Ответственный', pickClient: 'Взять себе', unpickClient: 'Снять',
    manualLeadName: 'Имя лида', manualLeadSource: 'Источник', manualLeadOwner: 'Оператор', manualLeadNote: 'Заметка', addManualLead: 'Добавить лид',
    operatorsTitle: 'Панель оператора', operatorsSubtitle: 'Рабочая зона оператора: задачи, клиенты и лиды.',
    textToOperators: 'Задача операторам', textToOperatorsPlaceholder: 'Напишите задачу для операторов...', saveAdminNote: 'Отправить задачу',
    adminNotes: 'История задач', noAdminNotes: 'Задач пока нет.', messagesFromClients: 'Сообщения клиентов',
    tasksFromAdmin: 'Задачи от админа', noTasksForYou: 'Вам пока не назначены задачи.',
    assignOne: 'Одному', assignGroup: 'Группе', assignAll: 'Всем операторам',
    operatorRanking: 'Рейтинг операторов', successfulDeals: 'Успешные сделки', downloadOperatorReport: 'Скачать PDF', operatorPanel: 'Панель оператора', adminPanel: 'Панель админа',
    operatorAccounts: 'Аккаунты операторов', operatorAccountsHint: 'Создайте логины операторов для этого бизнеса.', operatorId: 'ID оператора', operatorPassword: 'Пароль',
    addOperator: 'Добавить оператора', noOperators: 'Операторов пока нет.',
    igGrowthTitle: 'Instagram Growth Analyzer',
    igGrowthSubtitle: 'AI-рекомендации по качеству контента, engagement и конверсии.',
    igGrowthScore: 'Скор аккаунта',
    igGrowthProduct: 'Продукт для продвижения на этой неделе',
    igGrowthProblems: 'Основные проблемы',
    igGrowthNextContent: 'Рекомендуемый следующий контент',
    igGrowthWeeklyPlan: 'Недельный контент-план',
    igGrowthMonthlyPlan: 'Месячный фокус',
    igGrowthTasks: 'Задачи по улучшению аккаунта',
    igGrowthQuestions: 'Частые вопросы клиентов',
    igGrowthScope: 'Охват анализа',
    igGrowthLoading: 'Анализируем Instagram-активность...',
    igGrowthEmpty: 'Пока нет анализа. Подключите live-данные и обновите.',
    igGrowthRefresh: 'Обновить анализ',
    igGrowthRetry: 'Повторить',
    postsTitle: 'Посты',
    postsSubtitle: 'Импортируйте посты/reels Instagram и добавляйте доп. контекст для ответов бота.',
    importPosts: 'Импорт постов',
    refreshPosts: 'Обновить посты',
    postsLoading: 'Загрузка постов...',
    postsEmpty: 'Посты пока не импортированы.',
    postExtraInfo: 'Доп. информация по посту для ответов бота',
    savePostInfo: 'Сохранить информацию',
    postSaved: 'Информация по посту сохранена',
    videoAnalyzerTitle: 'Video Analyzer',
    videoAnalyzerSubtitle: 'Анализ Reels, TikTok и Shorts через Gemini.',
    videoAnalyzerUpload: 'Загрузить Reel, TikTok или Shorts',
    videoAnalyzerNiche: 'Ниша',
    videoAnalyzerDescription: 'Текущее описание',
    videoAnalyzerDetails: 'Детали видео',
    videoAnalyzerRun: 'Анализировать',
    videoAnalyzerLoading: 'Анализируем...',
    videoAnalyzerPreview: 'Превью видео',
    videoAnalyzerReport: 'AI отчет',
    videoAnalyzerMeta: 'Gemini анализ',
    videoAnalyzerEmpty: 'Загрузите видео или добавьте текстовые детали, затем запустите анализ.',
    copy: 'Копировать',
    copied: 'Скопировано',
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
    global_prompt: 'You are Milana Premium factory sales operator.',
    instagram_prompt: 'Instagram comment+DM rules:',
    telegram_prompt: 'Telegram sales rules:',
    whatsapp_prompt: 'WhatsApp sales rules:',
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
      `- Use first-touch identity line for new chats.`,
      `- For price/catalog details, handoff to manager when exact terms are needed.`,
      `- For Instagram price/catalog comments, send details in DM and never ask for name, phone, address, or other private information publicly.`,
      `- Collect only the order details needed, and use private chat for personal/contact information.`,
      `- Only answer Milana Premium sales topics: products, catalog, price/order flow, wholesale, delivery, payment, address, warranty, and manager handoff.`,
      `- Never answer unrelated topics. Refuse briefly and redirect to catalog or manager help.`,
      `- For price questions, do not invent exact prices; one qop/meshok is usually around 400-500 USD and exact terms go to manager.`,
      `- Never promise reservation and never invent price/stock/delivery details.`,
      `- Use +998501551010 for manager handoff when required.`,
      `- Do not repeat "${productHint}" or any product name in every message.`,
      goal ? `- Main improvement goal: ${goal}.` : '',
    ].filter(Boolean).join('\n'),
    explanation: 'Aligned with Milana Premium sales-agent Q&A style and handoff policy.',
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

function InstagramGrowthAnalyzerCard({ data, loading, error, onRefresh, w = WORKSPACE_TEXT.en }) {
  const score = Number(data?.account_score || 0);
  const categoryScores = data?.category_scores || {};
  const nextContent = Array.isArray(data?.recommended_next_content) ? data.recommended_next_content : [];
  const weeklyPlan = Array.isArray(data?.weekly_content_plan) ? data.weekly_content_plan : [];
  const monthlyPlan = Array.isArray(data?.monthly_content_plan) ? data.monthly_content_plan : [];
  const problems = Array.isArray(data?.problems) ? data.problems : [];
  const tasks = Array.isArray(data?.account_improvement_tasks) ? data.account_improvement_tasks : [];
  const questions = Array.isArray(data?.common_customer_questions) ? data.common_customer_questions : [];

  return (
    <section className="ig-growth-card">
      <div className="section-card-head">
        <div>
          <h3>{w.igGrowthTitle}</h3>
          <p>{w.igGrowthSubtitle}</p>
        </div>
        <button className="panel-btn" onClick={() => onRefresh?.()}>{w.igGrowthRefresh}</button>
      </div>

      {loading && <div className="ig-growth-state">{w.igGrowthLoading}</div>}
      {!loading && error && (
        <div className="ig-growth-state error">
          <span>{error}</span>
          <button className="panel-btn subtle" onClick={() => onRefresh?.()}>{w.igGrowthRetry}</button>
        </div>
      )}
      {!loading && !error && !data && <div className="ig-growth-state">{w.igGrowthEmpty}</div>}

      {!loading && !error && data && (
        <div className="ig-growth-body">
          <div className="ig-growth-score">
            <span>{w.igGrowthScore}</span>
            <b>{Number.isFinite(score) ? `${score}/100` : '0/100'}</b>
            <em>{w.igGrowthProduct}: {data?.product_to_promote_this_week || '—'}</em>
            <small>
              {data?.data_source ? `Source: ${String(data.data_source).replaceAll('_', ' ')}` : ''}
              {data?.fetched_at ? ` · Fetched: ${String(data.fetched_at).replace('T', ' ').slice(0, 16)} UTC` : ''}
            </small>
          </div>

          <div className="ig-growth-metrics">
            {Object.entries(categoryScores).map(([key, value]) => (
              <div className="metric-card rich" key={key}>
                <span>{String(key).replaceAll('_', ' ')}</span>
                <b>{value}</b>
              </div>
            ))}
          </div>

          <div className="ig-growth-grid">
            <div className="ig-growth-column">
              <h4>{w.igGrowthProblems}</h4>
              <ul>{problems.map((item, idx) => <li key={`p-${idx}`}>{item}</li>)}</ul>
            </div>
            <div className="ig-growth-column">
              <h4>{w.igGrowthNextContent}</h4>
              <ul>{nextContent.map((item, idx) => <li key={`n-${idx}`}>{item?.type ? `${item.type}: ` : ''}{item?.idea || ''}</li>)}</ul>
            </div>
            <div className="ig-growth-column">
              <h4>{w.igGrowthQuestions}</h4>
              <ul>{questions.map((item, idx) => <li key={`q-${idx}`}>{item?.theme || ''}{item?.count ? ` (${item.count})` : ''}</li>)}</ul>
            </div>
            <div className="ig-growth-column">
              <h4>{w.igGrowthTasks}</h4>
              <ul>{tasks.map((item, idx) => <li key={`t-${idx}`}>{item}</li>)}</ul>
            </div>
          </div>

          <div className="ig-growth-grid">
            <div className="ig-growth-column">
              <h4>{w.igGrowthWeeklyPlan}</h4>
              <ul>{weeklyPlan.map((item, idx) => <li key={`w-${idx}`}>{item}</li>)}</ul>
            </div>
            <div className="ig-growth-column">
              <h4>{w.igGrowthMonthlyPlan}</h4>
              <ul>{monthlyPlan.map((item, idx) => <li key={`m-${idx}`}>{item}</li>)}</ul>
            </div>
          </div>

          {data?.analysis_scope && (
            <p className="ig-growth-scope"><b>{w.igGrowthScope}:</b> {data.analysis_scope}</p>
          )}
        </div>
      )}
    </section>
  );
}

function PostsWorkspace({
  posts = [],
  loading = false,
  error = '',
  selectedPostId = '',
  onSelectPost,
  onImportPosts,
  onRefreshPosts,
  onSaveExtraInfo,
  selectedBusiness,
  onToast,
  w = WORKSPACE_TEXT.en,
}) {
  const selected = posts.find(item => item.post_id === selectedPostId) || posts[0] || null;
  const [draft, setDraft] = useState('');

  useEffect(() => {
    setDraft(selected?.extra_info || '');
  }, [selectedPostId, selected?.extra_info]);

  return (
    <section className="posts-workspace">
      <div className="section-card-head">
        <div>
          <h3>{w.postsTitle}</h3>
          <p>{w.postsSubtitle}</p>
        </div>
        <div className="panel-actions">
          <button className="panel-btn subtle" onClick={() => onRefreshPosts?.()}>{w.refreshPosts}</button>
          <button className="panel-btn" onClick={() => onImportPosts?.()}>{w.importPosts}</button>
        </div>
      </div>

      {loading && <div className="ig-growth-state">{w.postsLoading}</div>}
      {!loading && error && <div className="ig-growth-state error"><span>{error}</span></div>}
      {!loading && !error && !posts.length && <div className="ig-growth-state">{w.postsEmpty}</div>}

      <VideoAnalyzerWorkspace
        selectedBusiness={selectedBusiness}
        selectedPost={selected}
        onToast={onToast}
        w={w}
      />

      {!loading && !error && posts.length > 0 && (
        <div className="posts-grid">
          <div className="posts-list">
            {posts.map((post) => (
              <button
                key={post.post_id}
                className={`post-row ${selected?.post_id === post.post_id ? 'active' : ''}`}
                onClick={() => onSelectPost?.(post.post_id)}
              >
                <span className="post-row-head">
                  <b>{post.media_product_type || post.media_type || 'post'}</b>
                  <em>{(post.timestamp || '').slice(0, 10)}</em>
                </span>
                <p>{post.caption || post.permalink || post.post_id}</p>
                <span className="post-row-stats">❤ {post.like_count || 0} · 💬 {post.comments_count || 0}</span>
              </button>
            ))}
          </div>

          <div className="post-details">
            {selected && (
              <>
                <div className="post-preview">
                  {(selected.thumbnail_url || selected.media_url) && <img src={selected.thumbnail_url || selected.media_url} alt="post preview" />}
                  <div>
                    <h4>{selected.media_product_type || selected.media_type || 'post'}</h4>
                    <p>{selected.caption || '—'}</p>
                    {selected.permalink && <a href={selected.permalink} target="_blank" rel="noreferrer">{selected.permalink}</a>}
                  </div>
                </div>
                <label className="field-row prompt-row">
                  <span>{w.postExtraInfo}</span>
                  <textarea rows={6} value={draft} onChange={(e) => setDraft(e.target.value)} />
                </label>
                <div className="panel-actions">
                  <button onClick={() => onSaveExtraInfo?.(selected.post_id, draft)}>{w.savePostInfo}</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function cleanAnalyzerText(value = '') {
  return String(value || '')
    .replace(/\*\*/g, '')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/^\s*[*-]\s+/gm, '')
    .replace(/[ \t]+\n/g, '\n')
    .trim();
}

function splitAnalyzerSections(report = '') {
  const clean = cleanAnalyzerText(report);
  if (!clean) return [];
  const lines = clean.split('\n');
  const sections = [];
  let intro = [];
  let current = null;
  const headingPattern = /^([\p{Extended_Pictographic}\u2600-\u27BF]\s*)?(.{2,90})$/u;
  const reportHeadingPattern = /^(анализ видео|анализ описания|соответствие видео|ошибки|что хорошо|улучшенное описание|вирусные варианты|лучшие хэштеги|что повысит просмотры|дополнительные идеи|итоговая оценка|оценка контента)$/i;

  lines.forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      if (current) current.lines.push('');
      else if (intro.length) intro.push('');
      return;
    }

    const hasEmojiPrefix = /^[\p{Extended_Pictographic}\u2600-\u27BF]/u.test(line);
    const plainHeading = line
      .replace(/^[\p{Extended_Pictographic}\u2600-\u27BF]\s*/u, '')
      .trim();
    const isHeading = headingPattern.test(line) && reportHeadingPattern.test(plainHeading);

    if (isHeading) {
      if (!current && intro.join('\n').trim()) {
        sections.push({ title: 'Summary', body: intro.join('\n').trim() });
        intro = [];
      }
      if (current) sections.push({ title: current.title, body: current.lines.join('\n').trim() });
      current = { title: line, lines: [] };
      return;
    }

    if (current) current.lines.push(line);
    else intro.push(line);
  });

  if (current) sections.push({ title: current.title, body: current.lines.join('\n').trim() });
  else if (intro.join('\n').trim()) sections.push({ title: 'AI report', body: intro.join('\n').trim() });
  return sections.filter(section => section.title || section.body);
}

function AnalyzerSectionBody({ body }) {
  const blocks = String(body || '').split(/\n{2,}/).filter(Boolean);
  return (
    <div className="analyzer-section-body">
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n').map(line => line.trim()).filter(Boolean);
        const listLike = lines.length > 1 || lines.every(line => /^([^:]{2,48}):\s+/.test(line));
        if (listLike) {
          return (
            <ul key={`block-${blockIndex}`}>
              {lines.map((line, lineIndex) => {
                const match = line.match(/^([^:]{2,48}):\s+(.+)$/);
                return (
                  <li key={`line-${lineIndex}`}>
                    {match ? <><strong>{match[1]}</strong><span>{match[2]}</span></> : <span>{line}</span>}
                  </li>
                );
              })}
            </ul>
          );
        }
        return <p key={`block-${blockIndex}`}>{lines.join(' ')}</p>;
      })}
    </div>
  );
}

function AnalyzerReport({ report, meta, errorText = '', emptyText, onCopy, w = WORKSPACE_TEXT.en }) {
  const sections = splitAnalyzerSections(report);
  const hasReport = sections.length > 0;
  const [activeSection, setActiveSection] = useState(0);
  const [copiedKey, setCopiedKey] = useState('');

  useEffect(() => {
    if (!sections.length) {
      setActiveSection(0);
      return;
    }
    setActiveSection(0);
  }, [report]);

  const copySection = async (key, text, label) => {
    const ok = await onCopy?.(text, label);
    if (ok === false) return;
    setCopiedKey(key);
    window.clearTimeout(copySection.timer);
    copySection.timer = window.setTimeout(() => setCopiedKey(''), 1600);
  };

  const currentSection = sections[activeSection] || sections[0] || null;

  return (
    <div className="video-result">
      <div className="video-result-head">
        <div>
          <strong>{w.videoAnalyzerReport || 'AI report'}</strong>
          <span>{meta || (w.videoAnalyzerMeta || 'Gemini analysis')}</span>
        </div>
        <button className="copy-btn" disabled={!hasReport} onClick={() => copySection('all', cleanAnalyzerText(report), w.videoAnalyzerReport || 'AI report')}>
          {copiedKey === 'all' ? (w.copied || 'Copied') : (w.copy || 'Copy')}
        </button>
      </div>
      {!hasReport ? (
        <div className={`video-result-empty ${errorText ? 'error' : ''}`}>{errorText || emptyText}</div>
      ) : (
        <div className="analyzer-report-layout">
          <nav className="analyzer-section-nav" aria-label={w.videoAnalyzerReport || 'AI report'}>
            {sections.map((section, index) => (
              <button
                key={`${section.title}-${index}`}
                className={`analyzer-section-tab ${activeSection === index ? 'active' : ''}`}
                onClick={() => setActiveSection(index)}
              >
                <span className="analyzer-section-tab-index">{String(index + 1).padStart(2, '0')}</span>
                <span className="analyzer-section-tab-title">{section.title}</span>
              </button>
            ))}
          </nav>
          {currentSection && (
            <article className="analyzer-section-detail">
              <header className="analyzer-section-detail-head">
                <div className="analyzer-section-detail-title">
                  <strong>{currentSection.title}</strong>
                  <span>{w.videoAnalyzerSectionLabel || 'Selected section'}</span>
                </div>
                <button className="copy-btn subtle" onClick={() => copySection(`section-${activeSection}`, `${currentSection.title}\n${currentSection.body}`.trim(), currentSection.title)}>
                  {copiedKey === `section-${activeSection}` ? (w.copied || 'Copied') : (w.copy || 'Copy')}
                </button>
              </header>
              <div className="analyzer-section-detail-body">
                <AnalyzerSectionBody body={currentSection.body} />
              </div>
            </article>
          )}
        </div>
      )}
    </div>
  );
}

function VideoAnalyzerWorkspace({ selectedBusiness, selectedPost, onToast, w = WORKSPACE_TEXT.en }) {
  const [videoFile, setVideoFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState('');
  const [brand, setBrand] = useState(selectedBusiness?.business_name || '');
  const [niche, setNiche] = useState(selectedBusiness?.business_type || 'Fashion / product sales');
  const [description, setDescription] = useState('');
  const [details, setDetails] = useState('');
  const [model, setModel] = useState('gemini-3-flash-preview');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState('');
  const [meta, setMeta] = useState('');
  const [errorText, setErrorText] = useState('');
  const descriptionRef = useRef(null);

  useEffect(() => {
    if (!brand && selectedBusiness?.business_name) setBrand(selectedBusiness.business_name);
    if (!niche && selectedBusiness?.business_type) setNiche(selectedBusiness.business_type);
  }, [selectedBusiness?.business_name, selectedBusiness?.business_type]);

  useEffect(() => {
    if (!description && selectedPost?.caption) setDescription(selectedPost.caption);
    if (!details && selectedPost?.extra_info) setDetails(selectedPost.extra_info);
  }, [selectedPost?.post_id]);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const selectVideo = (event) => {
    const file = event.target.files?.[0] || null;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setVideoFile(file);
    setPreviewUrl(file ? URL.createObjectURL(file) : '');
    setMeta(file ? `${file.name} · ${Math.round((file.size / 1024 / 1024) * 10) / 10} MB` : '');
  };

  const analyze = async () => {
    setLoading(true);
    setResult('');
    setErrorText('');
    try {
      const captured = videoFile ? await captureVideoFramesFromFile(videoFile, 4) : { frames: [], duration: 0 };
      const response = await API.postJson('/api/v2/video-analyzer/analyze', {
        description,
        brand,
        niche,
        details,
        model,
        duration: captured.duration,
        frames: captured.frames,
      }, { timeoutMs: 320000 });
      const data = response?.data || {};
      setResult(data.report || '');
      setMeta(`Gemini · ${data.model || model} · ${captured.frames.length} frames`);
      setErrorText('');
      onToast?.('Video analysis ready');
    } catch (e) {
      setResult('');
      setMeta('Analyzer failed');
      setErrorText(e.message || 'Video analysis failed');
      onToast?.(e.message || 'Video analysis failed');
    } finally {
      setLoading(false);
    }
  };

  const copyText = async (text, label = '') => {
    const clean = cleanAnalyzerText(text);
    if (!clean) return false;
    try {
      await navigator.clipboard?.writeText(clean);
      onToast?.(`${label || 'Text'} copied`);
      window.setTimeout(() => {
        descriptionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        descriptionRef.current?.focus();
      }, 80);
      return true;
    } catch (e) {
      onToast?.('Copy failed');
      return false;
    }
  };

  return (
    <section className="video-analyzer-workspace">
      <div className="section-card-head video-analyzer-head">
        <div>
          <h3>{w.videoAnalyzerTitle || 'Video Analyzer'}</h3>
          <p>{w.videoAnalyzerSubtitle || 'Analyze Reels, TikToks, and Shorts with Gemini.'}</p>
        </div>
      </div>
      <div className="video-analyzer-form">
        <label className="video-upload">
          <input type="file" accept="video/*" onChange={selectVideo} />
          <I.Photo />
          <span>{videoFile ? videoFile.name : (w.videoAnalyzerUpload || 'Upload Reel, TikTok, or Shorts')}</span>
        </label>
        <div className="model-grid">
          <label className="field-row">
            <span>{w.brand || 'Brand'}</span>
            <input value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="Milana Premium" />
          </label>
          <label className="field-row">
            <span>{w.videoAnalyzerNiche || 'Niche'}</span>
            <input value={niche} onChange={(e) => setNiche(e.target.value)} placeholder="Fashion, beauty, food..." />
          </label>
        </div>
        <label className="field-row">
          <span>{w.videoAnalyzerDescription || 'Current caption'}</span>
          <textarea ref={descriptionRef} value={description} onChange={(e) => setDescription(e.target.value)} rows={5} placeholder="Paste the current Instagram/TikTok/Shorts caption." />
        </label>
        <label className="field-row">
          <span>{w.videoAnalyzerDetails || 'Video details'}</span>
          <textarea value={details} onChange={(e) => setDetails(e.target.value)} rows={4} placeholder="What is shown, product name, audience, offer, or context." />
        </label>
        <div className="model-grid">
          <label className="field-row">
            <span>{w.model || 'Model'}</span>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="gemini-3-flash-preview">gemini-3-flash-preview</option>
              <option value="gemini-2.5-flash">gemini-2.5-flash</option>
              <option value="gemini-3.1-pro-preview">gemini-3.1-pro-preview</option>
            </select>
          </label>
          <button className="panel-btn video-analyzer-run" disabled={loading || (!videoFile && !description.trim() && !details.trim())} onClick={analyze}>
            {loading ? (w.videoAnalyzerLoading || 'Analyzing...') : (w.videoAnalyzerRun || 'Analyze')}
          </button>
        </div>
      </div>

      <div className="video-analyzer-output">
        {previewUrl ? (
          <video src={previewUrl} controls playsInline preload="metadata" />
        ) : (
          <div className="video-preview-empty">{w.videoAnalyzerPreview || 'Video preview'}</div>
        )}
      </div>

      <div className="video-analyzer-report-pane">
        <AnalyzerReport
          report={result}
          meta={meta}
          errorText={errorText}
          emptyText={w.videoAnalyzerEmpty || 'Upload a video or add text details, then run analysis.'}
          onCopy={copyText}
          w={w}
        />
      </div>
    </section>
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

function ClientsTable({
  conversations,
  leadStages,
  leadPrices,
  onOpenConversation,
  clientOwners = {},
  manualClients = [],
  manualLeads = [],
  operatorAccounts = [],
  onAddManualClient = () => {},
  onRemoveManualClient = () => {},
  onAddManualLead = () => {},
  onRemoveManualLead = () => {},
  onLeadStageChange = () => {},
  onLeadPriceChange = () => {},
  currentUser = null,
  onPickClient = () => {},
  w,
}) {
  const currentOwnerLabel = userOwnerLabel(currentUser);
  const currentOwnerKeys = useMemo(() => userOwnerKeys(currentUser), [currentUser]);
  const [candidateId, setCandidateId] = useState('');
  const [manualLeadForm, setManualLeadForm] = useState({
    name: '',
    platform: 'telegram',
    owner: currentOwnerLabel,
    price: '',
    note: '',
  });
  useEffect(() => {
    setManualLeadForm(prev => prev.owner ? prev : { ...prev, owner: currentOwnerLabel });
  }, [currentOwnerLabel]);
  const operatorOptions = useMemo(() => {
    const options = [];
    const add = (value) => {
      const clean = String(value || '').trim();
      if (clean && !options.some(item => item.toLowerCase() === clean.toLowerCase())) options.push(clean);
    };
    add(currentOwnerLabel);
    (operatorAccounts || []).forEach(item => add(item?.login_id));
    Object.values(clientOwners || {}).forEach(add);
    return options;
  }, [currentOwnerLabel, operatorAccounts, clientOwners]);
  const conversationMap = useMemo(
    () => new Map((conversations || []).map(conv => [conv.id, conv])),
    [conversations],
  );
  const rows = useMemo(
    () => {
      const conversationRows = (manualClients || [])
      .map(id => conversationMap.get(id))
      .filter(Boolean)
      .map(conv => ({
        ...conv,
        stage: leadStages[conv.id] || guessLeadStage(conv),
        price: leadPrices[conv.id] || '',
        owner: String(clientOwners?.[conv.id] || '').trim(),
        sourceType: 'conversation',
      }));
      const manualRows = (manualLeads || [])
        .filter(Boolean)
        .map(lead => {
          const id = String(lead.id || '').trim();
          return {
            id,
            name: String(lead.name || 'Manual lead').trim(),
            handle: String(lead.note || '').trim() || '@manual',
            platform: String(lead.platform || 'manual').trim(),
            channelName: String(lead.platform || 'manual').trim(),
            stage: leadStages[id] || lead.stage || 'new',
            price: leadPrices[id] || lead.price || '',
            owner: String(clientOwners?.[id] || lead.operator || lead.owner || '').trim(),
            preview: String(lead.note || '').trim() || '-',
            unread: 0,
            avatar: avatarFor(String(lead.name || 'Manual lead'), id),
            sourceType: 'manual',
          };
        });
      return [...conversationRows, ...manualRows];
    },
    [manualClients, manualLeads, conversationMap, leadStages, leadPrices, clientOwners],
  );
  const availableCandidates = useMemo(
    () => (conversations || []).filter(conv => !(manualClients || []).includes(conv.id)),
    [conversations, manualClients],
  );

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
          <p>Important clients added manually by admin/operators.</p>
        </div>
        <span>{rows.length}</span>
      </div>
      <div className="panel-actions" style={{ marginBottom: 12 }}>
        <select value={candidateId} onChange={(e) => setCandidateId(e.target.value)}>
          <option value="">Select conversation...</option>
          {availableCandidates.map(conv => (
            <option key={conv.id} value={conv.id}>{conv.name} ({conv.handle})</option>
          ))}
        </select>
        <button
          onClick={() => {
            if (!candidateId) return;
            onAddManualClient(candidateId);
            setCandidateId('');
          }}
          disabled={!candidateId}
        >
          Add client
        </button>
      </div>
      <div className="manual-lead-form">
        <input
          value={manualLeadForm.name}
          placeholder={w.manualLeadName || 'Lead name'}
          onChange={(e) => setManualLeadForm(prev => ({ ...prev, name: e.target.value }))}
        />
        <select
          value={manualLeadForm.platform}
          aria-label={w.manualLeadSource || 'Source'}
          onChange={(e) => setManualLeadForm(prev => ({ ...prev, platform: e.target.value }))}
        >
          <option value="telegram">Telegram</option>
          <option value="whatsapp">WhatsApp</option>
          <option value="instagram">Instagram</option>
          <option value="phone">Phone</option>
          <option value="other">Other</option>
        </select>
        <select
          value={manualLeadForm.owner}
          aria-label={w.manualLeadOwner || 'Operator'}
          onChange={(e) => setManualLeadForm(prev => ({ ...prev, owner: e.target.value }))}
        >
          {operatorOptions.map(option => <option key={option} value={option}>{option}</option>)}
        </select>
        <input
          value={manualLeadForm.price}
          placeholder={w.leadPricePlaceholder || 'Add price'}
          onChange={(e) => setManualLeadForm(prev => ({ ...prev, price: e.target.value }))}
        />
        <input
          value={manualLeadForm.note}
          placeholder={w.manualLeadNote || 'Note'}
          onChange={(e) => setManualLeadForm(prev => ({ ...prev, note: e.target.value }))}
        />
        <button
          type="button"
          onClick={() => {
            if (!manualLeadForm.name.trim()) return;
            onAddManualLead(manualLeadForm);
            setManualLeadForm({ name: '', platform: 'telegram', owner: currentOwnerLabel, price: '', note: '' });
          }}
          disabled={!manualLeadForm.name.trim() || !manualLeadForm.owner.trim()}
        >
          {w.addManualLead || 'Add manual lead'}
        </button>
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
              <th>{w.ownerAssigned || 'Owner'}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {!rows.length && (
              <tr>
                <td colSpan="8" className="clients-empty">{w.clientsEmpty}</td>
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
                <td>
                  <select value={row.stage} onChange={(e) => onLeadStageChange(row.id, e.target.value)}>
                    {LEAD_STAGE_ORDER.map(option => (
                      <option key={option} value={option}>{stageNames[option]}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    className="client-price-input"
                    value={row.price || ''}
                    placeholder="-"
                    onChange={(e) => onLeadPriceChange(row.id, e.target.value)}
                  />
                </td>
                <td className="client-preview">{row.preview}</td>
                <td>{row.unread || 0}</td>
                <td>
                  {row.owner ? (
                    <span className="chip human" style={{ textTransform: 'none' }}>{row.owner}</span>
                  ) : (
                    <span style={{ opacity: 0.65 }}>-</span>
                  )}
                </td>
                <td style={{ display: 'flex', gap: 8 }}>
                  {row.sourceType === 'conversation' ? (
                    <button className="table-action" onClick={() => onOpenConversation(row.id)}>{w.leadOpen}</button>
                  ) : null}
                  {row.owner && currentOwnerKeys.has(row.owner.toLowerCase()) ? (
                    <button className="table-action" onClick={() => onPickClient(row.id, '')}>{w.unpickClient || 'Unpick'}</button>
                  ) : (
                    <button className="table-action" onClick={() => onPickClient(row.id, currentOwnerLabel)}>{w.pickClient || 'Pick me'}</button>
                  )}
                  <button className="table-action" onClick={() => row.sourceType === 'manual' ? onRemoveManualLead(row.id) : onRemoveManualClient(row.id)}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function userOwnerKeys(currentUser) {
  const keys = new Set();
  const add = (value) => {
    const raw = String(value || '').trim().toLowerCase();
    if (!raw) return;
    keys.add(raw);
    const short = raw.split('@')[0];
    if (short) keys.add(short);
  };
  add(currentUser?.ownerEmail);
  add(currentUser?.email);
  add(currentUser?.name);
  add(currentUser?.id);
  return keys;
}

function userOwnerLabel(currentUser) {
  const raw = String(currentUser?.ownerEmail || currentUser?.email || currentUser?.name || currentUser?.id || '').trim();
  if (!raw) return 'operator';
  return raw.split('@')[0] || raw;
}

function buildOperatorRankingRows({ leadStages = {}, clientOwners = {}, manualLeads = [], operatorDeals = {}, operatorAccounts = [] }) {
  const stats = new Map();
  const ensureRow = (id) => {
    const operatorId = String(id || '').trim();
    if (!operatorId) return null;
    const key = operatorId.toLowerCase();
    if (!stats.has(key)) {
      stats.set(key, {
        id: operatorId,
        name: operatorId.charAt(0).toUpperCase() + operatorId.slice(1),
        picked: 0,
        deals: 0,
      });
    }
    return stats.get(key);
  };

  const accountRows = Array.isArray(operatorAccounts)
    ? operatorAccounts
      .filter(item => String(item?.role || '').toLowerCase() === 'operator')
      .map(item => {
        const loginId = String(item?.login_id || '').trim();
        if (!loginId) return null;
        return ensureRow(loginId);
      })
      .filter(Boolean)
    : [];

  Object.entries(clientOwners || {}).forEach(([conversationId, owner]) => {
    const row = ensureRow(owner);
    if (!row) return;
    row.picked += 1;
    if (String(leadStages?.[conversationId] || '').toLowerCase() === 'won') row.deals += 1;
  });

  (manualLeads || []).forEach(lead => {
    const id = String(lead?.id || '').trim();
    if (!id || clientOwners?.[id]) return;
    const row = ensureRow(lead?.operator || lead?.owner);
    if (!row) return;
    row.picked += 1;
    if (String(leadStages?.[id] || lead?.stage || '').toLowerCase() === 'won') row.deals += 1;
  });

  Object.entries(operatorDeals || {}).forEach(([operatorId, value]) => {
    const row = ensureRow(operatorId);
    if (!row || row.deals > 0) return;
    const legacyDeals = Number(value || 0);
    if (Number.isFinite(legacyDeals) && legacyDeals > 0) row.deals = legacyDeals;
  });

  const rows = Array.from(stats.values());
  if (!rows.length && !accountRows.length) return [{ id: 'unassigned', name: 'Unassigned', picked: 0, deals: 0 }];
  return rows.sort((a, b) => (b.deals - a.deals) || (b.picked - a.picked) || a.name.localeCompare(b.name));
}

function OperatorsRanking({ leadStages, clientOwners = {}, manualLeads = [], operatorDeals = {}, operatorAccounts = [], onDownloadReport, reportDisabled = false, w }) {
  const rows = buildOperatorRankingRows({ leadStages, clientOwners, manualLeads, operatorDeals, operatorAccounts });

  return (
    <section className="operator-ranking">
      <div className="section-card-head">
        <div>
          <h3>{w.operatorRanking}</h3>
          <p>{w.successfulDeals}</p>
        </div>
        <button type="button" className="panel-btn" disabled={reportDisabled} onClick={onDownloadReport}>
          {w.downloadOperatorReport || 'Download PDF'}
        </button>
      </div>
      <div className="operator-rank-list">
        {rows.map((row, index) => (
          <div className="operator-rank-row" key={row.id}>
            <span className="rank-number">{index + 1}</span>
            <strong>{row.name}</strong>
            <span>{row.deals} {w.successfulDeals || 'successful deals'} · {row.picked} picked</span>
          </div>
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
        {(operatorsData || operators).map((operator, idx) => (
          <div key={operator.login_id} className="operator-account-item">
            <div className="operator-account-main">
              <strong>{operator.login_id}</strong>
              <small>ID #{idx + 1}</small>
            </div>
            <em className="operator-role-chip">{operator.role || 'operator'}</em>
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

function operatorRecipientKeys(currentUser) {
  const keys = new Set();
  const pushKey = (value) => {
    const raw = String(value || '').trim().toLowerCase();
    if (!raw) return;
    keys.add(raw);
    const username = raw.split('@')[0];
    if (username) keys.add(username);
  };
  pushKey(currentUser?.ownerEmail);
  pushKey(currentUser?.email);
  pushKey(currentUser?.name);
  pushKey(currentUser?.id);
  return keys;
}

function isTaskForOperator(note, keys) {
  const recipients = Array.isArray(note?.recipients)
    ? note.recipients.map(item => String(item || '').trim().toLowerCase()).filter(Boolean)
    : ['*'];
  if (!recipients.length || recipients.includes('*')) return true;
  return recipients.some(recipient => {
    if (keys.has(recipient)) return true;
    const username = recipient.split('@')[0];
    return username ? keys.has(username) : false;
  });
}

function OperatorTaskInboxCard({ adminNotes = [], currentUser, w }) {
  const keys = useMemo(() => operatorRecipientKeys(currentUser), [currentUser]);
  const tasks = useMemo(
    () => (adminNotes || []).filter(note => isTaskForOperator(note, keys)),
    [adminNotes, keys],
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
  const { conversations, leadStages, leadPrices, clientOwners, manualLeads, operatorDeals, adminNotes, onAdminNote, setLeadStage, setLeadPrice, onOpenConversation, selectedBusinessId, operatorAccounts, onReloadOperatorAccounts, onDownloadOperatorReport, w } = props;
  return (
    <div className="operator-panel">
      <AdminTaskDispatchCard adminNotes={adminNotes} onAdminNote={onAdminNote} operatorAccounts={operatorAccounts} w={w} />
      <OperatorMessagesCard conversations={conversations} onOpenConversation={onOpenConversation} w={w} />
      <OperatorAccountsPanel selectedBusinessId="" onToast={() => {}} w={w} readOnly operatorsData={operatorAccounts} onReload={onReloadOperatorAccounts} />
      <OperatorsRanking
        leadStages={leadStages}
        clientOwners={clientOwners}
        manualLeads={manualLeads}
        operatorDeals={operatorDeals}
        operatorAccounts={operatorAccounts}
        onDownloadReport={onDownloadOperatorReport}
        reportDisabled={!selectedBusinessId}
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
  const roleScope = resolveRoleScope(props.currentUser, props.businesses || []);
  const isOperator = roleScope.isOperator;
  if (isOperator) return <OperatorPanel {...props} />;
  return <AdminPanel {...props} />;
}

function WorkspacePanel({
  lang,
  t,
  view,
  stats,
  posts,
  postsLoading,
  postsError,
  selectedPostId,
  onSelectPost,
  onImportPosts,
  onRefreshPosts,
  onSavePostInfo,
  growthAnalyzer,
  growthAnalyzerLoading,
  growthAnalyzerError,
  onRefreshGrowthAnalyzer,
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
  clientOwners,
  manualClients,
  manualLeads,
  operatorDeals,
  adminNotes,
  operatorAccounts,
  onReloadOperatorAccounts,
  onLeadStageChange,
  onLeadPriceChange,
  onPickClient,
  onAddManualClient,
  onRemoveManualClient,
  onAddManualLead,
  onRemoveManualLead,
  onOperatorDealChange,
  onAdminNote,
  onDownloadOperatorReport,
  onOpenConversation,
  ownerEmail,
  onOwnerEmailSave,
  onSignOut,
  currentUser,
  userProfile,
  onUpdateUserProfile,
}) {
  const w = WORKSPACE_TEXT[lang] || WORKSPACE_TEXT.en;
  const roleScope = resolveRoleScope(currentUser, businesses || []);
  const isOperator = roleScope.isOperator;
  if (isOperator && !['leads', 'inbox', 'posts', 'clients', 'operators', 'profile'].includes(view)) return null;
  const selectedBusiness = businesses.find(b => b.id === selectedBusinessId) || businesses[0] || {};
  const activeProviderId = aiProviderForBusiness(selectedBusiness);
  const activeProvider = AI_PROVIDERS.find(provider => provider.id === activeProviderId) || AI_PROVIDERS[0];
  const activeModel = selectedBusiness.ai_model || activeProvider.defaultModel;
  const modelSelectValue = activeProvider.models.includes(activeModel) ? activeModel : 'custom';
  const title = {
    insights: t.insights,
    posts: t.posts || w.postsTitle,
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
        <>
          <InsightsDashboard conversations={conversations} stats={stats} w={w} />
          <InstagramGrowthAnalyzerCard
            data={growthAnalyzer}
            loading={growthAnalyzerLoading}
            error={growthAnalyzerError}
            onRefresh={onRefreshGrowthAnalyzer}
            w={w}
          />
        </>
      )}

      {view === 'posts' && (
        <PostsWorkspace
          posts={posts}
          loading={postsLoading}
          error={postsError}
          selectedPostId={selectedPostId}
          onSelectPost={onSelectPost}
          onImportPosts={onImportPosts}
          onRefreshPosts={onRefreshPosts}
          onSaveExtraInfo={onSavePostInfo}
          selectedBusiness={selectedBusiness}
          onToast={onToast}
          w={w}
        />
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
          businesses={businesses}
          currentUser={currentUser}
        />
      )}

      {view === 'clients' && (
        <ClientsTable
          conversations={conversations}
          leadStages={leadStages}
          leadPrices={leadPrices}
          clientOwners={clientOwners}
          manualClients={manualClients}
          manualLeads={manualLeads}
          operatorAccounts={operatorAccounts}
          onAddManualClient={onAddManualClient}
          onRemoveManualClient={onRemoveManualClient}
          onAddManualLead={onAddManualLead}
          onRemoveManualLead={onRemoveManualLead}
          onLeadStageChange={onLeadStageChange}
          onLeadPriceChange={onLeadPriceChange}
          currentUser={currentUser}
          onPickClient={onPickClient}
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
          clientOwners={clientOwners}
          manualLeads={manualLeads}
          adminNotes={adminNotes}
          operatorAccounts={operatorAccounts}
          onReloadOperatorAccounts={onReloadOperatorAccounts}
          onAdminNote={onAdminNote}
          onDownloadOperatorReport={onDownloadOperatorReport}
          setLeadStage={onLeadStageChange}
          setLeadPrice={onLeadPriceChange}
          onOpenConversation={onOpenConversation}
          currentUser={currentUser}
          businesses={businesses}
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
          {['products', 'prices', 'delivery_info', 'working_hours', 'faq', 'catalog_link', 'sales_phone', 'telegram_bag', 'knowledge'].map(key => (
            <label key={key}>
              <span>{w[key] || key.replaceAll('_', ' ')}</span>
              <textarea
                value={selectedBusiness[key] || ''}
                onChange={(e) => onBusinessSetting(selectedBusiness.id, { [key]: e.target.value }, false)}
                onBlur={(e) => onBusinessSetting(selectedBusiness.id, { [key]: e.target.value }, true)}
                rows={key === 'knowledge' || key === 'faq' ? 4 : key === 'telegram_bag' ? 3 : 2}
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
            <button onClick={() => { window.localStorage.removeItem('instaagent_dashboard_secret'); window.sessionStorage.removeItem('instaagent_dashboard_secret'); onToast('Dashboard secret cleared'); }}>Clear secret</button>
            <button onClick={() => navigator.clipboard?.writeText(API_BASE).then(() => onToast('API base copied'))}>Copy API base</button>
            <button onClick={onSignOut}>Sign out</button>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------- Rail ----------
function Rail({ t, activeView, onView, currentUser, userProfile, businesses }) {
  const roleScope = resolveRoleScope(currentUser, businesses || []);
  const isOperator = roleScope.isOperator;
  const items = [
    { id: 'leads', icon: <I.Star />, label: t.leads || 'Leads' },
    { id: 'inbox', icon: <I.Inbox />, label: t.inbox, dot: true },
    { id: 'posts', icon: <I.Photo />, label: t.posts || 'Posts' },
    { id: 'clients', icon: <I.Comment />, label: t.clients || 'Clients' },
    { id: 'operators', icon: <I.Phone />, label: t.operators || 'Operators' },
    { id: 'knowledge', icon: <I.Book />, label: t.knowledge },
    { id: 'prompts', icon: <I.Sparkle />, label: t.prompts || 'AI Prompts' },
    { id: 'accounts', icon: <I.Layers />, label: t.accounts },
  ].filter(item => !isOperator || ['leads', 'inbox', 'posts', 'clients', 'operators'].includes(item.id));
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
      {!isOperator && (
        <button className={`rail-btn ${activeView === 'settings' ? 'active' : ''}`} title={t.settings} onClick={() => onView('settings')}>
          <I.Sett />
          <span className="rail-label">{t.settings}</span>
        </button>
      )}
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
function Message({ m, conv, t, onReplyComment, onEditMessage, onDeleteMessage }) {
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
  const canManageOutbound = Boolean(
    conv?.platform === 'telegram' &&
    m.side === 'outbound' &&
    !m.pending &&
    m.id &&
    !String(m.id).startsWith('optimistic-')
  );
  return (
    <div className={`msg-group ${m.side} ${fromAi ? 'from-ai' : ''}`}>
      {m.type === 'text' && (
        <div className="bubble">{m.text}</div>
      )}
      {m.type === 'media' && (
        <div className="bubble media">
          {m.mediaKind === 'video' && isPlayableVideoUrl(m.mediaUrl) ? (
            <>
              <video className="media-video" src={m.mediaUrl} controls />
              <a className="open-post-link" href={m.mediaUrl} target="_blank" rel="noreferrer">
                Open media
              </a>
            </>
          ) : m.mediaUrl && (m.mediaKind === 'photo' || isRenderableImageUrl(m.mediaUrl)) && !isInstagramPostLink(m.mediaUrl) ? (
            <a href={m.mediaUrl} target="_blank" rel="noreferrer">
              <img className="media-img" src={m.mediaUrl} alt={m.label || 'attachment'} />
            </a>
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
        {m.pending && <span className="send-state">sending</span>}
        {m.failed && <span className="send-state failed">failed</span>}
        {m.side === 'outbound' && !m.failed && <span className="check"><I.DoubleCheck /></span>}
        {canManageOutbound && (
          <span className="msg-actions">
            {m.type === 'text' && (
              <button type="button" onClick={() => onEditMessage?.(m)}>Edit</button>
            )}
            <button type="button" className="danger" onClick={() => onDeleteMessage?.(m)}>Delete</button>
          </span>
        )}
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
function ThreadHead({ conv, aiOn, onToggleAi, canToggleAi = true, t, onPin, onArchive, onDelete, onMore, moreOpen }) {
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
        {canToggleAi && (
          <button className={`ai-toggle ${aiOn ? 'on' : ''}`} onClick={onToggleAi}>
            <span className="switch" />
            <span className="label-i">{aiOn ? t.aiOn : t.aiOff}</span>
          </button>
        )}
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
function ThreadColumn({ conv, aiOn, onToggleAi, t, messages, onSend, onEditMessage, onDeleteMessage, sending, threadLoading, onTool }) {
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
    if (!text) return;
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
        {threadLoading && (!messages || messages.length === 0) && <div className="empty">Loading conversation…</div>}
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
              <Message
                m={m}
                conv={conv}
                t={t}
                onReplyComment={selectReplyTarget}
                onEditMessage={onEditMessage}
                onDeleteMessage={onDeleteMessage}
              />
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
            <button className={`send ${draft.trim() ? '' : 'disabled'}`} onClick={sendDraft}>
              <I.Send /> {t.send}
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
function TopBar({ t, lang, setLang, theme, setTheme, conv, aiOn, canToggleAi = true, activeView, onToggleAi, onRefresh, onToast, onPin, onArchive, onDelete, onMore, moreOpen, onOpenProfile, onSignOut, userProfile, onUpdateUserProfile }) {
  const [accountOpen, setAccountOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const fileInputRef = useRef(null);
  const w = WORKSPACE_TEXT[lang] || WORKSPACE_TEXT.en;
  const workspaceNames = { inbox: t.inbox, insights: t.insights, posts: t.posts || w.postsTitle, knowledge: t.knowledge, prompts: w.promptsTitle, accounts: t.accounts, settings: t.settings, profile: w.profile };
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
          canToggleAi={canToggleAi}
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
              <button onClick={() => { window.localStorage.removeItem('instaagent_dashboard_secret'); window.sessionStorage.removeItem('instaagent_dashboard_secret'); onToast('Dashboard secret cleared'); }}>Clear secret</button>
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

function App({ lang, setLang, onSignOut, onAuthExpired, currentUser }) {
  const t = window.STRINGS[lang];
  const cachedConversationsRef = useRef(loadCachedConversations());
  const cachedThreadsRef = useRef(loadCachedThreads());
  const hasCachedInbox = cachedConversationsRef.current.items.length > 0;
  const [booting, setBooting] = useState(!hasCachedInbox);

  const [conversations, setConversations] = useState(() => cachedConversationsRef.current.items);
  const [selectedId, setSelectedId] = useState(() => cachedConversationsRef.current.selectedId || cachedConversationsRef.current.items[0]?.id || '');
  const [threads, setThreads] = useState(() => cachedThreadsRef.current);
  const [loading, setLoading] = useState(false);
  const [threadLoading, setThreadLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [apiError, setApiError] = useState('');
  const [liveMode, setLiveMode] = useState(false);
  const [stats, setStats] = useState(null);
  const [posts, setPosts] = useState([]);
  const [postsLoading, setPostsLoading] = useState(false);
  const [postsError, setPostsError] = useState('');
  const [selectedPostId, setSelectedPostId] = useState('');
  const [growthAnalyzer, setGrowthAnalyzer] = useState(null);
  const [growthAnalyzerLoading, setGrowthAnalyzerLoading] = useState(false);
  const [growthAnalyzerError, setGrowthAnalyzerError] = useState('');
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
  const [clientOwners, setClientOwners] = useState(() => readStoredObject(CLIENT_OWNERS_STORAGE_KEY));
  const [manualClients, setManualClients] = useState(() => {
    const stored = readStoredObject(MANUAL_CLIENTS_STORAGE_KEY);
    return Array.isArray(stored.items) ? stored.items : [];
  });
  const [manualLeads, setManualLeads] = useState(() => {
    const stored = readStoredObject(MANUAL_LEADS_STORAGE_KEY);
    return Array.isArray(stored.items) ? stored.items : [];
  });
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
  const threadWarmupRunningRef = useRef(0);
  const threadWarmupQueueRef = useRef([]);
  const threadWarmupSeenRef = useRef(new Set());
  const threadLoadPromisesRef = useRef({});
  const localOutboundMessagesRef = useRef({});
  const businessesRef = useRef([]);
  const workspaceStateHydratedRef = useRef(false);
  const workspaceStateTimersRef = useRef({});
  const seenOperatorTaskIdsRef = useRef(new Set());
  const conv = conversations.find(c => c.id === selectedId);
  const aiOn = conv ? conv.aiOn : false;
  const cachedSelectedMessages = getThreadMessages(threads[selectedId]);
  const messages = cachedSelectedMessages.length
    ? cachedSelectedMessages
    : (conv?.preview
      ? [{
        id: `preview-${selectedId || 'thread'}`,
        side: 'inbound',
        type: 'text',
        time: conv?.lastTime || '',
        text: conv?.preview || '',
        isPreview: true,
      }]
      : window.getThread(selectedId));
  const roleScope = resolveRoleScope(currentUser, businesses);
  const isOperator = roleScope.isOperator;
  const currentOwnerLabel = userOwnerLabel(currentUser);

  const [theme, setTheme] = useState(TWEAK_DEFAULTS.theme);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    writeStoredObject(CACHED_CONVERSATIONS_STORAGE_KEY, {
      items: conversations,
      selectedId: selectedId || conversations[0]?.id || '',
      updatedAt: Date.now(),
    });
  }, [conversations, selectedId]);

  useEffect(() => {
    writeStoredObject(CACHED_THREADS_STORAGE_KEY, {
      items: trimThreadCache(threads),
      updatedAt: Date.now(),
    });
  }, [threads]);

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
    if (!isOperator) return;
    const keys = operatorRecipientKeys(currentUser);
    const visibleTasks = (operatorAdminNotes || []).filter(note => isTaskForOperator(note, keys));
    if (!visibleTasks.length) return;

    const seen = seenOperatorTaskIdsRef.current;
    if (!seen.size) {
      visibleTasks.forEach(task => seen.add(String(task.id)));
      return;
    }

    const fresh = visibleTasks.filter(task => !seen.has(String(task.id)));
    if (!fresh.length) return;
    fresh.forEach(task => seen.add(String(task.id)));
    showToast(`New task from admin: ${fresh[0]?.text || ''}`.trim());
  }, [isOperator, currentUser, operatorAdminNotes]);

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

  const loadGrowthAnalyzer = async (businessId = selectedBusinessId, { silent = false, noCache = false } = {}) => {
    const business = String(businessId || '').trim();
    if (!business) {
      setGrowthAnalyzer(null);
      setGrowthAnalyzerError('');
      return null;
    }
    if (!silent) setGrowthAnalyzerLoading(true);
    try {
      const data = await API.get(`/api/v2/instagram-growth-analyzer?business_id=${encodeURIComponent(business)}&days=30&no_cache=${noCache ? '1' : '0'}`);
      setGrowthAnalyzer(data?.data || null);
      setGrowthAnalyzerError('');
      return data?.data || null;
    } catch (e) {
      setGrowthAnalyzer(null);
      setGrowthAnalyzerError(e.message || 'Could not load growth analysis');
      return null;
    } finally {
      if (!silent) setGrowthAnalyzerLoading(false);
    }
  };

  const resolveBusinessId = (candidate = '') => {
    const direct = String(candidate || '').trim();
    if (direct) return direct;
    const selected = String(selectedBusinessId || '').trim();
    if (selected) return selected;
    const fromCurrentConversation = String((conv || {}).businessId || '').trim();
    if (fromCurrentConversation) return fromCurrentConversation;
    const fromSelectedConversation = String(
      (conversations || []).find(item => item.id === (selectedIdRef.current || selectedId))?.businessId || '',
    ).trim();
    if (fromSelectedConversation) return fromSelectedConversation;
    const fromConversationList = String((conversations || []).find(item => item.businessId)?.businessId || '').trim();
    if (fromConversationList) return fromConversationList;
    const fromRef = String((businessesRef.current || [])[0]?.id || '').trim();
    if (fromRef) return fromRef;
    const fromState = String((businesses || [])[0]?.id || '').trim();
    return fromState;
  };

  const loadInstagramPosts = async (businessId = selectedBusinessId, { refresh = false, silent = false } = {}) => {
    let business = resolveBusinessId(businessId);
    if (!business) {
      await loadBusinesses({ silent: true });
      business = resolveBusinessId(businessId);
    }
    if (!business) {
      setPosts([]);
      setSelectedPostId('');
      setPostsError('');
      return [];
    }
    if (!silent) setPostsLoading(true);
    try {
      const data = await API.get(
        `/api/v2/instagram-posts?business_id=${encodeURIComponent(business)}&refresh=${refresh ? '1' : '0'}&limit=300`,
        { timeoutMs: refresh ? 180000 : 60000 },
      );
      const rows = Array.isArray(data?.data) ? data.data : [];
      setPosts(rows);
      setSelectedPostId((current) => (rows.some(item => item.post_id === current) ? current : (rows[0]?.post_id || '')));
      setPostsError('');
      return rows;
    } catch (e) {
      setPosts([]);
      setSelectedPostId('');
      setPostsError(e.message || 'Could not load posts');
      return [];
    } finally {
      if (!silent) setPostsLoading(false);
    }
  };

  const importInstagramPosts = async (businessId = selectedBusinessId) => {
    let business = resolveBusinessId(businessId);
    if (!business) {
      await loadBusinesses({ silent: true });
      business = resolveBusinessId(businessId);
    }
    if (!business) {
      showToast('No business found. Please connect/select a business first.');
      return [];
    }
    if (!String(selectedBusinessId || '').trim() || String(selectedBusinessId).trim() !== business) {
      setSelectedBusinessId(business);
    }
    setPostsLoading(true);
    try {
      const data = await API.postJson(
        '/api/v2/instagram-posts/import',
        { business_id: business, max_items: 300 },
        { timeoutMs: 180000 },
      );
      const rows = Array.isArray(data?.data) ? data.data : [];
      setPosts(rows);
      setSelectedPostId(rows[0]?.post_id || '');
      setPostsError('');
      showToast(`Imported ${rows.length} posts`);
      return rows;
    } catch (e) {
      setPostsError(e.message || 'Could not import posts');
      showToast(e.message || 'Could not import posts');
      return [];
    } finally {
      setPostsLoading(false);
    }
  };

  const saveInstagramPostInfo = async (postId, extraInfo) => {
    const business = resolveBusinessId(selectedBusinessId);
    if (!business || !postId) return;
    try {
      await API.postJson('/api/v2/instagram-posts/extra-info', {
        business_id: business,
        post_id: postId,
        extra_info: extraInfo || '',
      });
      setPosts(items => items.map(item => item.post_id === postId ? { ...item, extra_info: extraInfo || '' } : item));
      showToast((WORKSPACE_TEXT[lang] || WORKSPACE_TEXT.en).postSaved);
    } catch (e) {
      showToast(e.message || 'Could not save post info');
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
      if (state.client_owners && typeof state.client_owners === 'object') {
        setClientOwners(state.client_owners);
        writeStoredObject(CLIENT_OWNERS_STORAGE_KEY, state.client_owners);
      }
      if (state.manual_clients && typeof state.manual_clients === 'object') {
        const clientIds = Array.isArray(state.manual_clients.items) ? state.manual_clients.items.map(String).filter(Boolean) : [];
        setManualClients(clientIds);
        writeStoredObject(MANUAL_CLIENTS_STORAGE_KEY, { items: clientIds });
      }
      if (state.manual_leads && typeof state.manual_leads === 'object') {
        const leads = Array.isArray(state.manual_leads.items) ? state.manual_leads.items.filter(Boolean) : [];
        setManualLeads(leads);
        writeStoredObject(MANUAL_LEADS_STORAGE_KEY, { items: leads });
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

  const loadOperatorTasks = async (businessId = selectedBusinessId, { forMe = true, silent = true } = {}) => {
    const business = String(businessId || '').trim();
    if (!business || !liveModeRef.current) return [];
    try {
      const data = await API.get(`/api/v2/operator-tasks?business_id=${encodeURIComponent(business)}&for_me=${forMe ? '1' : '0'}`);
      const rows = Array.isArray(data?.data) ? data.data : [];
      setOperatorAdminNotes(rows);
      writeStoredObject(OPERATOR_ADMIN_NOTES_STORAGE_KEY, { items: rows });
      return rows;
    } catch (e) {
      if (!silent) showToast(e.message || 'Could not load tasks');
      return [];
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

  const downloadOperatorReport = async () => {
    const business = resolveBusinessId(selectedBusinessId);
    if (!business) {
      showToast('Select a business first');
      return;
    }
    try {
      const response = await API.fetchWithTimeout(
        `${API_BASE}${scopedPath(`/api/v2/operator-deals/report.pdf?business_id=${encodeURIComponent(business)}`)}`,
        { headers: apiHeaders() },
        45000,
      );
      if (!response.ok) {
        let message = `Request failed: ${response.status}`;
        try {
          const data = await response.json();
          message = apiErrorMessage(data, response.status);
        } catch (e) {
          // PDF endpoint may not return JSON on infrastructure errors.
        }
        throw new Error(message);
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `operator-deals-${business}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      showToast('Operator report downloaded');
    } catch (e) {
      showToast(e.message || 'Could not download report');
    }
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
      loadInstagramPosts(selectedBusinessId, { refresh: false, silent: true }),
      loadGrowthAnalyzer(selectedBusinessId, { silent: true, noCache: true }),
      loadOperatorAccounts(selectedBusinessId),
      loadWorkspaceState(selectedBusinessId),
      loadOperatorTasks(selectedBusinessId, { forMe: isOperator, silent: true }),
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

  const rememberedLocalOutboundMessages = (conversationId) => {
    const now = Date.now();
    const rows = localOutboundMessagesRef.current[conversationId] || [];
    const fresh = rows.filter(message => (now - Number(message.sentAt || now)) <= LOCAL_OUTBOUND_TTL_MS);
    localOutboundMessagesRef.current[conversationId] = fresh;
    return fresh;
  };

  const rememberLocalOutboundMessage = (conversationId, message) => {
    if (!conversationId || !message?.id) return;
    const existing = rememberedLocalOutboundMessages(conversationId).filter(item => item.id !== message.id);
    localOutboundMessagesRef.current[conversationId] = [...existing, message];
  };

  const updateLocalOutboundMessage = (conversationId, messageId, updates) => {
    if (!conversationId || !messageId) return;
    localOutboundMessagesRef.current[conversationId] = rememberedLocalOutboundMessages(conversationId).map(item => (
      item.id === messageId ? { ...item, ...updates } : item
    ));
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
      const data = await API.get('/api/v2/conversations?no_cache=1&fast=1', { timeoutMs: 25000 });
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
        .map(item => item.id === selectedCurrent ? clearConversationUnread(item) : item)
        .map(item => {
          const localMessages = rememberedLocalOutboundMessages(item.id);
          const latestLocal = localMessages[localMessages.length - 1];
          if (!latestLocal) return item;
          return {
            ...item,
            preview: latestLocal.text,
            lastTime: 'now',
            lastFromMe: true,
            kpis: { ...(item.kpis || {}), last: 'now' },
          };
        });
      if (!next.length) {
        setConversations([]);
        setSelectedId('');
        setLiveMode(true);
        setApiError('');
        return true;
      }
      setConversations(next);
      setSelectedId(current => next.some(c => c.id === current) ? current : next[0].id);
      setLiveMode(true);
      setApiError('');
      // Warm all threads in background so chat switches feel instant.
      window.setTimeout(() => warmupConversationThreads(next, selectedCurrent), 0);
      if (sideLoad) {
        loadStats();
        loadBusinesses({ silent: true });
      }
      return true;
    } catch (e) {
      const isAbort = /aborted|aborterror|signal is aborted/i.test(String(e?.message || ''));
      if (silent) {
        if (!isAbort) setApiError(`Live sync delayed: ${e.message}`);
        return false;
      }
      if (isLocalDevDashboardMode()) {
        setLiveMode(true);
        setApiError('');
        setConversations([]);
        setSelectedId('');
        return false;
      }
      setLiveMode(false);
      setApiError(isAbort ? 'Loading... please wait' : `Loading... please wait (${e.message})`);
      // Keep cached conversations visible when live sync is slow/failing.
      if (!conversations.length) {
        setConversations([]);
        setSelectedId('');
      }
      return false;
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    if (!apiError) return;
    if (!/unauthorized/i.test(String(apiError))) return;
    onAuthExpired?.();
  }, [apiError, onAuthExpired]);

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

  const loadThread = async (conversationId, { silent = false, markRead = true, limit = 200, noCache = false } = {}) => {
    if (!conversationId || !liveMode) return;
    const inFlight = threadLoadPromisesRef.current[conversationId];
    if (inFlight) return inFlight;
    if (!silent) setThreadLoading(true);
    const request = (async () => {
      try {
        const data = await API.get(`/api/v2/conversation/${encodeURIComponent(conversationId)}/messages?mark_read=${markRead ? '1' : '0'}&limit=${Math.max(1, Number(limit || 200))}&no_cache=${noCache ? '1' : '0'}`);
        const normalized = (data.data || []).map(normalizeMessage);
        setThreads(prev => ({
          ...prev,
          [conversationId]: {
            updatedAt: Date.now(),
            messages: mergeLocalOutboundMessages(
              normalized,
              getThreadMessages(prev[conversationId]),
              rememberedLocalOutboundMessages(conversationId)
            ),
          },
        }));
        setConversations(rows => rows.map(item => item.id === conversationId ? clearConversationUnread(item) : item));
        setApiError('');
        return true;
      } catch (e) {
        setApiError(`${e.message} Showing cached messages.`);
        return false;
      } finally {
        delete threadLoadPromisesRef.current[conversationId];
        if (!silent) setThreadLoading(false);
      }
    })();
    threadLoadPromisesRef.current[conversationId] = request;
    return request;
  };

  const pumpThreadWarmupQueue = () => {
    if (!liveModeRef.current) return;
    while (
      threadWarmupRunningRef.current < THREAD_WARMUP_CONCURRENCY &&
      threadWarmupQueueRef.current.length > 0
    ) {
      const conversationId = threadWarmupQueueRef.current.shift();
      const currentMessages = getThreadMessages(threads[conversationId]);
      if (!conversationId || currentMessages.length > 0) continue;
      threadWarmupRunningRef.current += 1;
      loadThread(conversationId, { silent: true, markRead: false, limit: 120, noCache: true })
        .catch(() => false)
        .finally(() => {
          threadWarmupRunningRef.current = Math.max(0, threadWarmupRunningRef.current - 1);
          pumpThreadWarmupQueue();
        });
    }
  };

  const warmupConversationThreads = (rows = [], priorityId = '') => {
    const queue = [];
    if (priorityId) queue.push(priorityId);
    for (const row of rows || []) {
      if (row?.id) queue.push(row.id);
    }
    for (const conversationId of queue) {
      if (!conversationId) continue;
      const currentMessages = getThreadMessages(threads[conversationId]);
      if (currentMessages.length > 0) continue;
      const seen = threadWarmupSeenRef.current;
      if (seen.has(conversationId)) continue;
      seen.add(conversationId);
      threadWarmupQueueRef.current.push(conversationId);
    }
    pumpThreadWarmupQueue();
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
    const targetConv = conv;

    if (!liveMode) {
      const localMessage = {
        id: `local-${Date.now()}`,
        side: 'outbound',
        type: 'text',
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        text,
      };
      setThreads(prev => {
        const existing = prev[targetConv.id]?.messages || prev[targetConv.id] || [];
        return {
          ...prev,
          [targetConv.id]: {
            updatedAt: Date.now(),
            messages: [...existing, localMessage],
          },
        };
      });
      return true;
    }

    const optimisticId = `optimistic-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const optimisticMessage = {
      id: optimisticId,
      side: 'outbound',
      type: 'text',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      text,
      local: true,
      pending: true,
      sentAt: Date.now(),
    };
    rememberLocalOutboundMessage(targetConv.id, optimisticMessage);
    setThreads(prev => {
      const existing = prev[targetConv.id]?.messages || prev[targetConv.id] || [];
      return {
        ...prev,
        [targetConv.id]: {
          updatedAt: Date.now(),
          messages: [...existing, optimisticMessage],
        },
      };
    });
    setConversations(rows => rows.map(item => item.id === targetConv.id ? {
      ...item,
      preview: text,
      lastTime: 'now',
      lastFromMe: true,
      kpis: { ...(item.kpis || {}), last: 'now' },
    } : item));

    (async () => {
      try {
        await sendLiveMessage(targetConv, text, options);
        updateLocalOutboundMessage(targetConv.id, optimisticId, { pending: false, failed: false, error: '' });
        setThreads(prev => {
          const existing = prev[targetConv.id]?.messages || prev[targetConv.id] || [];
          const nextMessages = existing.map(item => (
            item.id === optimisticId
              ? { ...item, pending: false, failed: false, error: '' }
              : item
          ));
          return {
            ...prev,
            [targetConv.id]: {
              updatedAt: Date.now(),
              messages: nextMessages,
            },
          };
        });
        window.setTimeout(() => {
          loadThread(targetConv.id, { silent: true, limit: 300, noCache: true });
          loadConversations({ silent: true, sideLoad: false });
        }, 1500);
        showToast('Message sent');
      } catch (e) {
        updateLocalOutboundMessage(targetConv.id, optimisticId, { pending: false, failed: true, error: e.message });
        setThreads(prev => {
          const existing = prev[targetConv.id]?.messages || prev[targetConv.id] || [];
          const nextMessages = existing.map(item => (
            item.id === optimisticId
              ? { ...item, pending: false, failed: true, error: e.message }
              : item
          ));
          return {
            ...prev,
            [targetConv.id]: {
              updatedAt: Date.now(),
              messages: nextMessages,
            },
          };
        });
        setApiError(e.message);
        showToast(e.message);
      }
    })();

    return true;
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
    if (!selectedBusinessId || !liveMode || activeView !== 'insights') return;
    loadGrowthAnalyzer(selectedBusinessId, { silent: true });
  }, [selectedBusinessId, activeView, liveMode]);

  useEffect(() => {
    if (!selectedBusinessId || !liveMode || activeView !== 'posts') return;
    loadInstagramPosts(selectedBusinessId, { refresh: false, silent: true });
  }, [selectedBusinessId, activeView, liveMode]);

  useEffect(() => {
    if (liveMode) loadOperatorAccounts(selectedBusinessId);
  }, [selectedBusinessId, liveMode]);

  useEffect(() => {
    if (!selectedBusinessId || !liveMode) return;
    workspaceStateHydratedRef.current = false;
    loadWorkspaceState(selectedBusinessId);
  }, [selectedBusinessId, liveMode]);

  useEffect(() => {
    if (!selectedBusinessId || !liveMode) return;
    loadOperatorTasks(selectedBusinessId, { forMe: isOperator, silent: true });
  }, [selectedBusinessId, liveMode, isOperator]);

  useEffect(() => {
    const cached = getThreadMessages(threads[selectedId]);
    loadThread(selectedId, { silent: cached.length > 0, limit: 300, noCache: true });
  }, [selectedId, liveMode]);

  useEffect(() => {
    if (!liveMode) return undefined;

    const pollThread = async () => {
      const currentId = selectedIdRef.current;
      if (!currentId || threadPollBusy.current) return;
      threadPollBusy.current = true;
      try {
        await loadThread(currentId, { silent: true, noCache: true });
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

    const syncVisible = () => {
      if (document.hidden || !liveModeRef.current) return;
      pollThread();
      pollInbox();
      pollStats();
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

    document.addEventListener('visibilitychange', syncVisible);
    syncVisible();

    return () => {
      window.clearInterval(threadTimer);
      window.clearInterval(inboxTimer);
      window.clearInterval(statsTimer);
      document.removeEventListener('visibilitychange', syncVisible);
    };
  }, [liveMode]);

  const toggleAi = async () => {
    if (!conv) return;
    if (isOperator) {
      showToast('Only owner/admin can turn bots on or off');
      return;
    }
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

  const editMessage = async (message) => {
    if (!conv || !message?.id) return;
    if (conv.platform !== 'telegram') {
      showToast('Instagram and WhatsApp do not support editing already-delivered messages through the connected API.');
      return;
    }

    const currentText = String(message.text || '').trim();
    const nextText = window.prompt('Edit this Telegram message:', currentText);
    if (nextText === null) return;
    const cleanText = nextText.trim();
    if (!cleanText || cleanText === currentText) return;

    const conversationId = conv.id;
    setThreads(prev => {
      const existing = prev[conversationId]?.messages || prev[conversationId] || [];
      return {
        ...prev,
        [conversationId]: {
          updatedAt: Date.now(),
          messages: existing.map(item => item.id === message.id ? { ...item, text: cleanText } : item),
        },
      };
    });

    try {
      await API.postJson('/api/v2/message/edit', { message_id: message.id, text: cleanText });
      await loadThread(conversationId, { silent: true, limit: 300, noCache: true });
      await loadConversations({ silent: true, sideLoad: false });
      showToast('Message edited on Telegram');
    } catch (e) {
      setThreads(prev => {
        const existing = prev[conversationId]?.messages || prev[conversationId] || [];
        return {
          ...prev,
          [conversationId]: {
            updatedAt: Date.now(),
            messages: existing.map(item => item.id === message.id ? { ...item, text: currentText } : item),
          },
        };
      });
      setApiError(e.message);
      showToast(e.message);
    }
  };

  const deleteMessage = async (message) => {
    if (!conv || !message?.id) return;
    if (conv.platform !== 'telegram') {
      showToast('Instagram and WhatsApp do not support deleting already-delivered messages through the connected API.');
      return;
    }
    if (!window.confirm('Delete this message from the real Telegram chat and this dashboard?')) return;

    const conversationId = conv.id;
    try {
      await API.postJson('/api/v2/message/delete', { message_id: message.id });
      setThreads(prev => {
        const existing = prev[conversationId]?.messages || prev[conversationId] || [];
        return {
          ...prev,
          [conversationId]: {
            updatedAt: Date.now(),
            messages: existing.filter(item => item.id !== message.id),
          },
        };
      });
      await loadConversations({ silent: true, sideLoad: false });
      showToast('Message deleted from Telegram');
    } catch (e) {
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
    if (isOperator && !['leads', 'inbox', 'posts', 'clients', 'operators', 'profile'].includes(view)) {
      setActiveView('inbox');
      showToast('Operator access is limited to Leads, Inbox, Posts, Clients, Operators, and Profile');
      return;
    }
    if ((view === 'operators' || view === 'clients' || view === 'settings') && liveModeRef.current) {
      loadOperatorAccounts(selectedBusinessId);
    }
    setActiveView(view);
    const names = {
      inbox: t.inbox,
      insights: t.insights,
      posts: t.posts || 'Posts',
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

  const setClientOwner = (conversationId, owner) => {
    setClientOwners(prev => {
      const next = { ...prev };
      const clean = String(owner || '').trim();
      if (clean) next[conversationId] = clean;
      else delete next[conversationId];
      writeStoredObject(CLIENT_OWNERS_STORAGE_KEY, next);
      queueWorkspaceStateSave({ client_owners: next });
      return next;
    });
    showToast(owner ? `Client picked by ${owner}` : 'Client unpicked');
  };

  const addManualClient = (conversationId) => {
    setManualClients(prev => {
      if (prev.includes(conversationId)) return prev;
      const next = [...prev, conversationId];
      writeStoredObject(MANUAL_CLIENTS_STORAGE_KEY, { items: next });
      queueWorkspaceStateSave({ manual_clients: { items: next } });
      return next;
    });
    showToast('Client added to important list');
  };

  const removeManualClient = (conversationId) => {
    setManualClients(prev => {
      const next = prev.filter(id => id !== conversationId);
      writeStoredObject(MANUAL_CLIENTS_STORAGE_KEY, { items: next });
      queueWorkspaceStateSave({ manual_clients: { items: next } });
      return next;
    });
    showToast('Client removed from important list');
  };

  const addManualLead = (lead = {}) => {
    const name = String(lead.name || '').trim();
    const owner = String(lead.owner || lead.operator || currentOwnerLabel).trim();
    if (!name || !owner) {
      showToast('Lead name and operator are required');
      return;
    }
    const id = `manual_lead_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
    const item = {
      id,
      name,
      platform: String(lead.platform || 'manual').trim(),
      operator: owner,
      note: String(lead.note || '').trim(),
      price: String(lead.price || '').trim(),
      stage: 'new',
      created_at: new Date().toISOString(),
    };
    setManualLeads(prev => {
      const next = [item, ...prev].slice(0, 500);
      writeStoredObject(MANUAL_LEADS_STORAGE_KEY, { items: next });
      queueWorkspaceStateSave({ manual_leads: { items: next } });
      return next;
    });
    setClientOwner(id, owner);
    setLeadStage(id, 'new');
    if (item.price) setLeadPrice(id, item.price);
    showToast(`Manual lead assigned to ${owner}`);
  };

  const removeManualLead = (leadId) => {
    const id = String(leadId || '').trim();
    if (!id) return;
    setManualLeads(prev => {
      const next = prev.filter(item => String(item?.id || '') !== id);
      writeStoredObject(MANUAL_LEADS_STORAGE_KEY, { items: next });
      queueWorkspaceStateSave({ manual_leads: { items: next } });
      return next;
    });
    setClientOwners(prev => {
      const next = { ...prev };
      delete next[id];
      writeStoredObject(CLIENT_OWNERS_STORAGE_KEY, next);
      queueWorkspaceStateSave({ client_owners: next });
      return next;
    });
    setLeadStages(prev => {
      const next = { ...prev };
      delete next[id];
      writeStoredObject(LEAD_STAGES_STORAGE_KEY, next);
      queueWorkspaceStateSave({ lead_stages: next });
      return next;
    });
    setLeadPrices(prev => {
      const next = { ...prev };
      delete next[id];
      writeStoredObject(LEAD_PRICES_STORAGE_KEY, next);
      queueWorkspaceStateSave({ lead_prices: next });
      return next;
    });
    showToast('Manual lead removed');
  };

  const addOperatorAdminNote = async (text, recipients = ['*'], mode = 'all') => {
    const business = String(selectedBusinessId || '').trim();
    const clean = String(text || '').trim();
    if (!clean || !business) {
      showToast('Select business and task text');
      return;
    }

    if (!liveModeRef.current) {
      setOperatorAdminNotes(prev => {
        const next = [{
          id: `${Date.now()}`,
          text: clean,
          recipients,
          assign_mode: mode,
          created_at: new Date().toISOString(),
        }, ...prev].slice(0, 50);
        writeStoredObject(OPERATOR_ADMIN_NOTES_STORAGE_KEY, { items: next });
        queueWorkspaceStateSave({ operator_admin_notes: { items: next } });
        return next;
      });
      showToast('Task saved locally');
      return;
    }

    try {
      await API.postJson('/api/v2/operator-tasks', {
        business_id: business,
        text: clean,
        recipients,
        assign_mode: mode,
      });
      await loadOperatorTasks(business, { forMe: isOperator, silent: true });
      showToast('Task sent to operators');
    } catch (e) {
      showToast(e.message || 'Could not send task');
    }
  };

  const selectConversation = (conversationId) => {
    setSelectedId(conversationId);
    setActiveView('inbox');
    setMoreOpen(false);
    warmupConversationThreads(conversations, conversationId);
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
          canToggleAi={!isOperator}
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
        <Rail t={t} activeView={activeView} onView={changeView} currentUser={currentUser} userProfile={userProfile} businesses={businesses} />
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
            onEditMessage={editMessage}
            onDeleteMessage={deleteMessage}
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
            posts={posts}
            postsLoading={postsLoading}
            postsError={postsError}
            selectedPostId={selectedPostId}
            onSelectPost={setSelectedPostId}
            onImportPosts={() => importInstagramPosts(selectedBusinessId)}
            onRefreshPosts={() => loadInstagramPosts(selectedBusinessId, { refresh: true })}
            onSavePostInfo={saveInstagramPostInfo}
            growthAnalyzer={growthAnalyzer}
            growthAnalyzerLoading={growthAnalyzerLoading}
            growthAnalyzerError={growthAnalyzerError}
            onRefreshGrowthAnalyzer={() => loadGrowthAnalyzer(selectedBusinessId, { noCache: true })}
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
            clientOwners={clientOwners}
            manualClients={manualClients}
            manualLeads={manualLeads}
            operatorDeals={operatorDeals}
            adminNotes={operatorAdminNotes}
            operatorAccounts={operatorAccounts}
            onReloadOperatorAccounts={() => loadOperatorAccounts(selectedBusinessId)}
            onLeadStageChange={setLeadStage}
            onLeadPriceChange={setLeadPrice}
            onPickClient={setClientOwner}
            onAddManualClient={addManualClient}
            onRemoveManualClient={removeManualClient}
            onAddManualLead={addManualLead}
            onRemoveManualLead={removeManualLead}
            onOperatorDealChange={setOperatorDealCount}
            onAdminNote={addOperatorAdminNote}
            onDownloadOperatorReport={downloadOperatorReport}
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
  const localDevSession = localDevDashboardSession();
  const forceDashboard = Boolean(urlParams.get('api') || urlParams.get('secret') || readAuthSession()?.token);
  const [showDashboard, setShowDashboard] = useState(() => {
    const hasDashboardHash = window.location.hash === DASHBOARD_HASH;
    const forceDashboard = urlParams.get('dashboard') === '1';
    const hasApiContext = Boolean(urlParams.get('api') || urlParams.get('secret'));
    const hasAuthToken = Boolean(readAuthSession()?.token);
    return hasDashboardHash || forceDashboard || hasApiContext || hasAuthToken;
  });
  const [currentUser, setCurrentUser] = useState(() => readAuthSession() || localDevSession || null);
  const [signedIn, setSignedIn] = useState(() => {
    const auth = readAuthSession();
    return !!(auth?.token || localDevSession?.token);
  });

  useEffect(() => {
    window.localStorage.setItem(UI_LANG_STORAGE_KEY, lang);
  }, [lang]);

  useEffect(() => {
    if (!localDevSession?.token) return;
    saveAuthSession(localDevSession.ownerEmail, localDevSession);
    setCurrentUser((current) => current?.token ? current : localDevSession);
    setSignedIn(true);
  }, [localDevSession?.ownerEmail, localDevSession?.role, localDevSession?.token]);

  useEffect(() => {
    const onHashChange = () => setShowDashboard(window.location.hash === DASHBOARD_HASH);
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    if (!showDashboard && !forceDashboard) return;
    if (!showDashboard && forceDashboard) setShowDashboard(true);
    if (window.location.hash === DASHBOARD_HASH) return;
    window.location.hash = DASHBOARD_HASH;
  }, [showDashboard, forceDashboard]);

  const openDashboard = () => {
    window.location.hash = DASHBOARD_HASH;
    setShowDashboard(true);
  };

  const backToLanding = () => {
    window.location.hash = '';
    setShowDashboard(false);
  };

  const signOut = () => {
    clearAuthSession();
    setCurrentUser(null);
    setSignedIn(false);
    backToLanding();
  };

  const authExpired = () => {
    clearAuthSession();
    setCurrentUser(null);
    setSignedIn(false);
    window.location.hash = DASHBOARD_HASH;
    setShowDashboard(true);
  };

  if (!showDashboard && !forceDashboard) return <LandingPage onOpenDashboard={openDashboard} lang={lang} setLang={setLang} />;
  if (!signedIn) return <SignInPage lang={lang} onSignedIn={(session) => { setCurrentUser(session || readAuthSession() || localDevSession); setSignedIn(true); }} onBack={backToLanding} />;
  return <App lang={lang} setLang={setLang} onSignOut={signOut} onAuthExpired={authExpired} currentUser={currentUser || readAuthSession()} />;
}

createRoot(document.getElementById('root')).render(<Root />);
