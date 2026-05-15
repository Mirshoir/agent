/* global window */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { createRoot } from 'react-dom/client';

import './app.css';
import './tweaks-panel.jsx';
import './data.jsx';
import './icons.jsx';

const I = window.I;

const ENV_API_BASE = import.meta.env.VITE_API_URL || 'https://agent-1-xi6h.onrender.com';
const ENV_DASHBOARD_SECRET = import.meta.env.VITE_DASHBOARD_SECRET || '';

const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('clear_auth')) {
  window.localStorage.removeItem('instaagent_dashboard_secret');
}
const API_BASE = (
  urlParams.get('api') ||
  ENV_API_BASE ||
  window.INSTAAGENT_API_BASE ||
  window.localStorage.getItem('instaagent_api_base')
).replace(/\/$/, '');

const DASHBOARD_SECRET =
  urlParams.get('secret') ||
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

const API = {
  async get(path) {
    const res = await fetch(`${API_BASE}${path}`, { headers: apiHeaders() });
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
  async post(path, params = {}) {
    const qs = new URLSearchParams(params);
    const res = await fetch(`${API_BASE}${path}?${qs.toString()}`, {
      method: 'POST',
      headers: apiHeaders(),
    });
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
  async postJson(path, body = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok || data.status === 'error' || data.error) throw new Error(apiErrorMessage(data, res.status));
    return data;
  },
};

const THREAD_POLL_MS = 2500;
const INBOX_POLL_MS = 6000;
const STATS_POLL_MS = 20000;

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
  const description = data?.meta?.description || data?.details?.description;
  const errorCode = data?.meta?.error_code || data?.details?.error_code;
  if (description) return errorCode ? `${description} (${errorCode})` : description;

  const message =
    data?.message ||
    data?.error ||
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

function hashHue(value) {
  let hash = 0;
  for (const ch of String(value || 'client')) hash = ((hash << 5) - hash) + ch.charCodeAt(0);
  return Math.abs(hash) % 360;
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
  if (platform === 'whatsapp') return channel === 'whatsapp_cloud' || !channel ? 'WhatsApp Cloud' : channel;
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
  const lastAt = row.last_message_at || row.created_at || row.lastAt || '';
  return {
    id: row.id,
    apiId: row.id,
    businessId: row.business_id || row.businessId || parsedBusinessId,
    customerId,
    chatId,
    channel,
    channelName,
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
    mediaFileId: row.media_file_id || getWhatsAppMediaId(row),
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

function ToggleRow({ label, hint, checked, onChange }) {
  return (
    <div className="toggle-row">
      <div>
        <strong>{label}</strong>
        {hint && <span>{hint}</span>}
      </div>
      <button className={`ai-toggle ${checked ? 'on' : ''}`} onClick={() => onChange(!checked)}>
        <span className="switch" />
        <span className="label-i">{checked ? 'On' : 'Off'}</span>
      </button>
    </div>
  );
}

function SecretField({ business, provider, onBusinessSetting }) {
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
        <span>{provider.label} key</span>
        <input
          type="password"
          value={value}
          placeholder={savedPreview ? `Saved (${savedPreview})` : 'Paste API key'}
          onChange={(e) => setValue(e.target.value)}
          onBlur={save}
          autoComplete="off"
        />
      </label>
      <button type="button" className="panel-btn subtle" disabled={!savedPreview} onClick={clear}>Clear</button>
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

function WorkspacePanel({
  view,
  stats,
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
}) {
  const selectedBusiness = businesses.find(b => b.id === selectedBusinessId) || businesses[0] || {};
  const activeProviderId = aiProviderForBusiness(selectedBusiness);
  const activeProvider = AI_PROVIDERS.find(provider => provider.id === activeProviderId) || AI_PROVIDERS[0];
  const activeModel = selectedBusiness.ai_model || activeProvider.defaultModel;
  const modelSelectValue = activeProvider.models.includes(activeModel) ? activeModel : 'custom';
  const title = {
    insights: 'Insights',
    knowledge: 'Knowledge',
    prompts: 'AI Prompt Settings',
    accounts: 'Accounts',
    settings: 'Settings',
    profile: 'Profile',
  }[view] || 'Workspace';

  if (view === 'inbox') return null;

  return (
    <section className="workspace-panel">
      <div className="workspace-head">
        <div>
          <h2>{title}</h2>
          <p>{selectedBusiness.business_name || 'Live backend workspace'}</p>
        </div>
        <button className="panel-btn" onClick={onRefresh}>Refresh</button>
      </div>

      {view === 'insights' && (
        <div className="workspace-grid">
          <div className="metric-card"><span>Total accounts</span><b>{stats?.total_accounts ?? 0}</b></div>
          <div className="metric-card"><span>Active accounts</span><b>{stats?.active_accounts ?? 0}</b></div>
          <div className="metric-card"><span>Instagram messages</span><b>{stats?.instagram_messages ?? 0}</b></div>
          <div className="metric-card"><span>Telegram messages</span><b>{stats?.telegram_messages ?? 0}</b></div>
          <div className="metric-card"><span>WhatsApp messages</span><b>{stats?.whatsapp_messages ?? 0}</b></div>
        </div>
      )}

      {view === 'accounts' && (
        <div className="account-list">
          {businesses.map(b => (
            <button key={b.id} className={`account-row ${b.id === selectedBusinessId ? 'active' : ''}`} onClick={() => onSelectBusiness(b.id)}>
              <Avatar data={avatarFor(b.business_name || b.instagram_business_id || 'Business', b.id)} size={38} platform={b.oauth_provider === 'whatsapp' ? 'whatsapp' : 'instagram'} />
              <span>
                <strong>{b.business_name || 'Unnamed business'}</strong>
                <em>{b.oauth_provider || b.business_type || 'business'} · {b.bot_enabled ? 'active' : 'paused'}</em>
              </span>
            </button>
          ))}
          {!businesses.length && <div className="empty">No businesses returned from the backend.</div>}
          <div className="panel-actions">
            <button onClick={() => window.open(`${API_BASE}/connect-instagram`, '_blank')}>Connect Instagram</button>
            <button onClick={() => window.open(`${API_BASE}/connect-facebook`, '_blank')}>Connect Facebook</button>
          </div>
        </div>
      )}

      {view === 'knowledge' && (
        <div className="knowledge-view">
          {['products', 'prices', 'delivery_info', 'working_hours', 'faq', 'catalog_link', 'sales_phone', 'knowledge'].map(key => (
            <label key={key}>
              <span>{key.replaceAll('_', ' ')}</span>
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
            <h3>Global Prompt</h3>
            <PromptField
              label="Used by Instagram + Telegram + WhatsApp"
              value={promptSettings.global_prompt}
              rows={7}
              onChange={(value) => onPromptSetting('global_prompt', value)}
            />
          </div>

          <div className="settings-section">
            <h3>Platform Overrides</h3>
            <PromptField
              label="Instagram rules"
              value={promptSettings.instagram_prompt}
              onChange={(value) => onPromptSetting('instagram_prompt', value)}
            />
            <PromptField
              label="Telegram rules"
              value={promptSettings.telegram_prompt}
              onChange={(value) => onPromptSetting('telegram_prompt', value)}
            />
            <PromptField
              label="WhatsApp rules"
              value={promptSettings.whatsapp_prompt}
              onChange={(value) => onPromptSetting('whatsapp_prompt', value)}
            />
          </div>

          <div className="settings-section">
            <h3>Business Knowledge</h3>
            <p className="section-hint">Products, prices, delivery, FAQ, contacts, and catalog links are managed in the Knowledge page and injected into the final prompt automatically.</p>
            <div className="prompt-knowledge-grid">
              <span>Products</span>
              <span>Prices</span>
              <span>Delivery</span>
              <span>FAQ</span>
              <span>Contacts</span>
              <span>Catalog links</span>
            </div>
          </div>

          <div className="settings-section">
            <h3>Sales Behavior</h3>
            <PromptField
              label="Opening message"
              value={promptSettings.opening_message}
              rows={4}
              onChange={(value) => onPromptSetting('opening_message', value)}
            />
            <PromptField
              label="Lead collection rules"
              value={promptSettings.lead_collection_rules}
              onChange={(value) => onPromptSetting('lead_collection_rules', value)}
            />
            <PromptField
              label="Follow-up style"
              value={promptSettings.sales_rules}
              onChange={(value) => onPromptSetting('sales_rules', value)}
            />
            <PromptField
              label="Human handoff rules"
              value={promptSettings.handoff_rules}
              onChange={(value) => onPromptSetting('handoff_rules', value)}
            />
          </div>

          <div className="panel-actions">
            <button disabled={promptLoading || promptSaving || !selectedBusiness.id} onClick={onSavePromptSettings}>
              {promptSaving ? 'Saving...' : 'Save AI prompt settings'}
            </button>
            <button onClick={() => onToast('Final prompt = Global prompt + Business knowledge + Platform-specific prompt + Conversation memory')}>
              Prompt formula
            </button>
          </div>
        </div>
      )}

      {view === 'settings' && (
        <div className="settings-view">
          <ToggleRow
            label="Bot enabled"
            hint="Controls automatic replies for this business."
            checked={!!selectedBusiness.bot_enabled}
            onChange={(enabled) => onBusinessSetting(selectedBusiness.id, { bot_enabled: enabled }, true)}
          />
          <ToggleRow
            label="Instagram DMs"
            hint="Automatic Instagram direct-message replies."
            checked={selectedBusiness.auto_reply_dms !== false}
            onChange={(enabled) => onBusinessSetting(selectedBusiness.id, { auto_reply_dms: enabled }, true)}
          />
          <ToggleRow
            label="Instagram comments"
            hint="Automatic comment replies."
            checked={selectedBusiness.auto_reply_comments !== false}
            onChange={(enabled) => onBusinessSetting(selectedBusiness.id, { auto_reply_comments: enabled }, true)}
          />
          <label className="field-row">
            <span>Language</span>
            <input value={selectedBusiness.language || ''} onChange={(e) => onBusinessSetting(selectedBusiness.id, { language: e.target.value }, false)} onBlur={(e) => onBusinessSetting(selectedBusiness.id, { language: e.target.value }, true)} />
          </label>
          <label className="field-row">
            <span>Tone</span>
            <input value={selectedBusiness.tone || ''} onChange={(e) => onBusinessSetting(selectedBusiness.id, { tone: e.target.value }, false)} onBlur={(e) => onBusinessSetting(selectedBusiness.id, { tone: e.target.value }, true)} />
          </label>
          <div className="settings-section">
            <h3>AI model</h3>
            <div className="model-grid">
              <label className="field-row">
                <span>Provider</span>
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
                <span>Model</span>
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
                  <option value="custom">Custom model</option>
                </select>
              </label>
            </div>
            <label className="field-row">
              <span>Custom model</span>
              <input
                value={activeModel}
                onChange={(e) => onBusinessSetting(selectedBusiness.id, { ai_model: e.target.value }, false)}
                onBlur={(e) => onBusinessSetting(selectedBusiness.id, { ai_model: e.target.value.trim() || activeProvider.defaultModel }, true)}
              />
            </label>
            <div className="model-grid">
              <label className="field-row">
                <span>Temperature</span>
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
                <span>Max tokens</span>
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
              Provider, model, temperature, and API keys stay here. Sales prompts now live in AI Prompt Settings so Instagram, Telegram, and WhatsApp share one source of truth.
            </p>
          </div>
          <div className="settings-section">
            <h3>API keys</h3>
            <div className="key-grid">
              {AI_PROVIDERS.map(provider => (
                <SecretField
                  key={provider.id}
                  business={selectedBusiness}
                  provider={provider}
                  onBusinessSetting={onBusinessSetting}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      {view === 'profile' && (
        <div className="settings-view">
          <div className="metric-card"><span>API base</span><b>{API_BASE}</b></div>
          <div className="panel-actions">
            <button onClick={() => { window.localStorage.removeItem('instaagent_dashboard_secret'); onToast('Dashboard secret cleared'); }}>Clear secret</button>
            <button onClick={() => navigator.clipboard?.writeText(API_BASE).then(() => onToast('API base copied'))}>Copy API base</button>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------- Rail ----------
function Rail({ t, activeView, onView }) {
  const items = [
    { id: 'inbox', icon: <I.Inbox />, label: t.inbox, dot: true },
    { id: 'insights', icon: <I.Chart />, label: t.insights },
    { id: 'knowledge', icon: <I.Book />, label: t.knowledge },
    { id: 'prompts', icon: <I.Sparkle />, label: 'AI Prompts' },
    { id: 'accounts', icon: <I.Layers />, label: t.accounts },
  ];
  return (
    <aside className="rail">
      {items.map(it => (
        <button key={it.id} className={`rail-btn ${activeView === it.id ? 'active' : ''}`} title={it.label} onClick={() => onView(it.id)}>
          {it.icon}
          {it.dot && <span className="dot" />}
        </button>
      ))}
      <div className="rail-spacer" />
      <button className={`rail-btn ${activeView === 'settings' ? 'active' : ''}`} title={t.settings} onClick={() => onView('settings')}><I.Sett /></button>
      <button className="rail-avatar" title="You" style={{ marginTop: 8 }} onClick={() => onView('profile')}>A</button>
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
          {c.lastFromMe && <span className="me">You · </span>}
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
function ListColumn({ conversations, selectedId, onSelect, t, loading, apiError, liveMode, onRefresh, onSaveSecret }) {
  const [filter, setFilter] = useState('all');
  const [platforms, setPlatforms] = useState({ instagram: true, telegram: true, whatsapp: true });
  const [search, setSearch] = useState('');
  const [secretDraft, setSecretDraft] = useState(window.localStorage.getItem('instaagent_dashboard_secret') || '');

  const counts = useMemo(() => ({
    all: conversations.length,
    needs: conversations.filter(c => c.needsHuman).length,
    unread: conversations.filter(c => c.unread > 0).length,
    ai: conversations.filter(c => c.aiOn && !c.needsHuman).length,
  }), [conversations]);

  const filtered = useMemo(() => {
    return conversations.filter(c => {
      if (!platforms[c.platform]) return false;
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
          <span>{liveMode ? 'Live backend · auto-sync' : 'Mock fallback'}</span>
          <button onClick={onRefresh} title="Refresh conversations">{loading ? 'Syncing' : 'Refresh'}</button>
        </div>
        {apiError && <div className="api-error">{apiError}</div>}
        {apiError.toLowerCase().includes('unauthorized') && (
          <div className="secret-box">
            <input
              type="password"
              placeholder="Dashboard secret"
              value={secretDraft}
              onChange={(e) => setSecretDraft(e.target.value)}
            />
            <button onClick={() => onSaveSecret(secretDraft)}>Connect</button>
          </div>
        )}
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
          <div className="empty">No conversations match.</div>
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
function Message({ m, conv, t }) {
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
  return (
    <div className={`msg-group ${m.side} ${fromAi ? 'from-ai' : ''}`}>
      {m.type === 'text' && (
        <div className="bubble">{m.text}</div>
      )}
      {m.type === 'media' && (
        <div className="bubble media">
          {m.mediaKind === 'video' && m.mediaUrl ? (
            <video className="media-video" src={m.mediaUrl} controls />
          ) : m.mediaUrl && (m.mediaKind === 'photo' || m.mediaUrl.match(/\.(png|jpe?g|webp|gif)(\?|$)/i)) ? (
            <img className="media-img" src={m.mediaUrl} alt={m.label || 'attachment'} />
          ) : m.mediaKind === 'file' ? (
            <div className="file-chip">
              <I.Paperclip />
              <span>{m.label || 'document'}</span>
            </div>
          ) : (
            <span className="ph" data-label={m.label || 'photo'} />
          )}
          {m.mediaCaption && <div className="cap">{m.mediaCaption}</div>}
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
    </div>
  );
}

// ---------- Thread head ----------
function ThreadHead({ conv, aiOn, onToggleAi, t, onPin, onArchive, onMore, moreOpen }) {
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
  const voiceRecordingSupported = ['telegram', 'whatsapp'].includes(conv.platform);

  const sendDraft = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft('');
    await onSend(text);
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

  let lastDay = null;

  return (
    <section className="thread-col">
      <div className="messages" ref={scrollRef}>
        {threadLoading && <div className="empty">Loading conversation…</div>}
        {groups.map(m => {
          const dayChanged = m.day && m.day !== lastDay;
          if (m.day) lastDay = m.day;
          return (
            <React.Fragment key={m.id}>
              {dayChanged && <div className="day-sep">{m.day}</div>}
              <Message m={m} conv={conv} t={t} />
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
            <button className={`tool-btn ${emojiOpen ? 'active' : ''}`} title="Emoji" onClick={() => setEmojiOpen(open => !open)}><I.Smile /></button>
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
            <div className="emoji-panel">
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
function DetailColumn({ conv, t, stats }) {
  if (!conv) return <aside className="detail-col" />;
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
          <span className="tag">Since {conv.customerSince}</span>
        </div>
      </div>

      <div className="detail-section">
        <h3>{t.summary} <em>· auto</em></h3>
        <div className="summary">{conv.summary}</div>
      </div>

      <div className="detail-section">
        <h3>Channel</h3>
        <div className="channel-facts">
          <span>Platform <b>{conv.platform}</b></span>
          <span>Channel <b>{conv.channelName || conv.channel || 'Inbox'}</b></span>
          <span>Customer <b>{conv.customerId}</b></span>
          <span>Chat <b>{conv.chatId || conv.customerId}</b></span>
          <span>Send via <b>{sendRouteFor(conv)}</b></span>
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
function TopBar({ t, lang, setLang, theme, setTheme, conv, aiOn, activeView, onToggleAi, onRefresh, onToast, onPin, onArchive, onMore, moreOpen }) {
  const [accountOpen, setAccountOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const workspaceNames = { inbox: 'Inbox', insights: 'Insights', knowledge: 'Knowledge', prompts: 'AI Prompt Settings', accounts: 'Accounts', settings: 'Settings', profile: 'Profile' };
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
          onMore={onMore}
          moreOpen={moreOpen}
        />
      ) : (
        <div className="topbar-thread workspace-top-title">
          <span>{workspaceNames[activeView] || 'Workspace'}</span>
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
            <span className="av">A</span>
            <span>Aziz</span>
            <I.Caret />
          </button>
          {profileOpen && (
            <div className="pop-menu profile-menu">
              <button onClick={() => onToast('Profile settings are local for now')}>Profile settings</button>
              <button onClick={() => { window.localStorage.removeItem('instaagent_dashboard_secret'); onToast('Dashboard secret cleared'); }}>Clear secret</button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

// ---------- App root ----------
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "light"
}/*EDITMODE-END*/;

function App() {
  const [lang, setLang] = useState('en');
  const t = window.STRINGS[lang];

  const [conversations, setConversations] = useState(window.CONVERSATIONS);
  const [selectedId, setSelectedId] = useState('c1');
  const [threads, setThreads] = useState(() => ({ ...window.THREADS }));
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
  const [promptSettings, setPromptSettings] = useState({});
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptSaving, setPromptSaving] = useState(false);
  const selectedIdRef = useRef(selectedId);
  const liveModeRef = useRef(liveMode);
  const threadPollBusy = useRef(false);
  const inboxPollBusy = useRef(false);
  const statsPollBusy = useRef(false);
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

  const showToast = (message) => {
    setToast(message);
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => setToast(''), 2200);
  };

  const loadStats = async () => {
    try {
      const data = await API.get('/api/v2/stats');
      setStats(data.data || null);
    } catch (e) {
      setStats(null);
    }
  };

  const loadBusinesses = async ({ silent = false } = {}) => {
    try {
      const data = await API.get('/api/businesses');
      const rows = data.data || [];
      setBusinesses(rows);
      setSelectedBusinessId(current => current || rows[0]?.id || '');
      return rows;
    } catch (e) {
      if (!silent) showToast(e.message);
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

  const updatePromptSetting = (key, value) => {
    setPromptSettings(settings => ({ ...settings, [key]: value }));
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
    await Promise.all([loadConversations({ sideLoad: false }), loadStats(), loadBusinesses(), loadPromptSettings(selectedBusinessId, { silent: true })]);
    showToast('Workspace refreshed');
  };

  const loadConversations = async ({ sideLoad = true, silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const data = await API.get('/api/v2/conversations');
      const selectedCurrent = selectedIdRef.current;
      const next = (data.data || [])
        .map(normalizeConversation)
        .map(item => item.id === selectedCurrent ? clearConversationUnread(item) : item);
      if (!next.length) throw new Error('No conversations returned from backend yet.');
      setConversations(next);
      setSelectedId(current => next.some(c => c.id === current) ? current : next[0].id);
      setLiveMode(true);
      setApiError('');
      if (sideLoad) {
        loadStats();
        loadBusinesses({ silent });
      }
      return true;
    } catch (e) {
      if (silent) {
        setApiError(`Live sync delayed: ${e.message}`);
        return false;
      }
      setLiveMode(false);
      setApiError(`${e.message} Using local demo data.`);
      setConversations(window.CONVERSATIONS);
      setThreads({ ...window.THREADS });
      setSelectedId(current => window.CONVERSATIONS.some(c => c.id === current) ? current : window.CONVERSATIONS[0]?.id);
      return false;
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const saveSecretAndRefresh = (secret) => {
    const clean = String(secret || '').trim();
    if (clean) {
      window.localStorage.setItem('instaagent_dashboard_secret', clean);
    } else {
      window.localStorage.removeItem('instaagent_dashboard_secret');
    }
    loadConversations();
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

  const sendLiveMessage = async (conversation, text) => {
    const result = await API.postJson('/api/v2/send-message', {
      conversation_id: conversation.apiId || conversation.id,
      text,
    });
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

  const sendMessage = async (text) => {
    if (!conv) return;

    if (!liveMode) {
      const localMessage = {
        id: `local-${Date.now()}`,
        side: 'outbound',
        type: 'text',
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        text,
      };
      setThreads(prev => ({ ...prev, [conv.id]: [...(prev[conv.id] || []), localMessage] }));
      return;
    }

    setSending(true);
    try {
      await sendLiveMessage(conv, text);
      await loadThread(conv.id);
      await loadConversations();
      showToast('Message sent');
    } catch (e) {
      setApiError(e.message);
      showToast(e.message);
    } finally {
      setSending(false);
    }
  };

  useEffect(() => {
    loadConversations();
  }, []);

  useEffect(() => {
    if (selectedBusinessId) loadPromptSettings(selectedBusinessId, { silent: true });
  }, [selectedBusinessId]);

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
    const nextEnabled = !conv.aiOn;
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
    setActiveView(view);
    const names = { inbox: 'Inbox', insights: 'Insights', knowledge: 'Knowledge', prompts: 'AI Prompt Settings', accounts: 'Accounts', settings: 'Settings', profile: 'Profile' };
    showToast(`${names[view] || view} selected`);
  };

  // Mark selected unread as read
  useEffect(() => {
    if (!selectedId) return;
    setConversations(cs => cs.map(c => c.id === selectedId ? clearConversationUnread(c) : c));
  }, [selectedId, liveMode]);

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
          onMore={() => setMoreOpen(v => !v)}
          moreOpen={moreOpen}
        />
        <Rail t={t} activeView={activeView} onView={changeView} />
        <ListColumn
          conversations={conversations}
          selectedId={selectedId}
          onSelect={setSelectedId}
          t={t}
          loading={loading}
          apiError={apiError}
          liveMode={liveMode}
          onRefresh={refreshWorkspace}
          onSaveSecret={saveSecretAndRefresh}
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
            view={activeView}
            stats={stats}
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
          />
        )}
        {activeView === 'inbox' && <DetailColumn conv={conv} t={t} stats={stats} />}
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

createRoot(document.getElementById('root')).render(<App />);
