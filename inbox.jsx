/* global React, ReactDOM, window */
const { useState, useEffect, useRef, useMemo } = React;
const I = window.I;

// API Configuration
const API_BASE_URL = window.location.origin;

function getAuthToken() {
  return sessionStorage.getItem('dashboardSecret') || localStorage.getItem('dashboardSecret') || '';
}

async function apiCall(endpoint, options = {}) {
  const token = getAuthToken();
  
  if (!token) {
    throw new Error('No authentication token');
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'x-dashboard-secret': token,
      ...options.headers
    }
  });

  if (!response.ok) {
    if (response.status === 401) {
      sessionStorage.clear();
      localStorage.clear();
      window.location.href = '/';
      throw new Error('Unauthorized');
    }
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || error.message || `API error: ${response.status}`);
  }

  return response.json();
}

// ============================================================================
// LOGIN PAGE
// ============================================================================
function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      // For now, use a simple test token
      // In production, you would call an actual login endpoint
      sessionStorage.setItem('dashboardSecret', 'test-secret');
      localStorage.setItem('user', JSON.stringify({ email, name: email.split('@')[0] }));
      
      window.location.reload();
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100vh',
      background: 'var(--bg)',
      flexDirection: 'column'
    }}>
      <div style={{
        padding: '40px',
        borderRadius: 'var(--radius-2)',
        background: 'var(--surface)',
        border: '1px solid var(--line)',
        width: '100%',
        maxWidth: '400px'
      }}>
        <h1 style={{ marginTop: 0, marginBottom: '24px' }}>Instaagent</h1>
        
        <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={loading}
            required
            style={{
              padding: '10px 12px',
              borderRadius: '8px',
              background: 'var(--surface-2)',
              border: '1px solid var(--line)',
              fontSize: '14px'
            }}
          />
          
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={loading}
            required
            style={{
              padding: '10px 12px',
              borderRadius: '8px',
              background: 'var(--surface-2)',
              border: '1px solid var(--line)',
              fontSize: '14px'
            }}
          />
          
          {error && (
            <div style={{
              color: 'var(--warn)',
              fontSize: '12px',
              padding: '8px 12px',
              background: 'var(--warn-soft)',
              borderRadius: '6px'
            }}>
              {error}
            </div>
          )}
          
          <button
            type="submit"
            disabled={loading}
            style={{
              padding: '10px',
              background: 'var(--accent)',
              color: 'var(--accent-ink)',
              borderRadius: '8px',
              fontWeight: '600',
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.6 : 1
            }}
          >
            {loading ? 'Logging in...' : 'Sign In'}
          </button>
        </form>

        <p style={{ textAlign: 'center', marginTop: '16px', fontSize: '12px', color: 'var(--muted)' }}>
          Demo: Use any email/password to login
        </p>
      </div>
    </div>
  );
}

// ============================================================================
// SMALL HELPERS
// ============================================================================
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

// ============================================================================
// RAIL
// ============================================================================
function Rail({ t }) {
  const items = [
    { id: 'inbox', icon: <I.Inbox />, label: t.inbox, dot: true, active: true },
    { id: 'insights', icon: <I.Chart />, label: t.insights },
    { id: 'knowledge', icon: <I.Book />, label: t.knowledge },
    { id: 'accounts', icon: <I.Layers />, label: t.accounts },
  ];
  return (
    <aside className="rail">
      {items.map(it => (
        <button key={it.id} className={`rail-btn ${it.active ? 'active' : ''}`} title={it.label}>
          {it.icon}
          {it.dot && <span className="dot" />}
        </button>
      ))}
      <div className="rail-spacer" />
      <button className="rail-btn" title={t.settings}><I.Sett /></button>
      <button className="rail-avatar" title="You">A</button>
    </aside>
  );
}

// ============================================================================
// CONVERSATION ROW
// ============================================================================
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

// ============================================================================
// LIST COLUMN
// ============================================================================
function ListColumn({ conversations, selectedId, onSelect, t }) {
  const [filter, setFilter] = useState('all');
  const [platforms, setPlatforms] = useState({ instagram: true, telegram: true, whatsapp: true });
  const [search, setSearch] = useState('');

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

// ============================================================================
// VOICE WAVE
// ============================================================================
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

// ============================================================================
// MESSAGE BUBBLE
// ============================================================================
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
          <span className="ph" data-label={m.label || 'photo'} />
          {m.mediaCaption && <div className="cap">{m.mediaCaption}</div>}
        </div>
      )}
      <div className="msg-time">{m.time}</div>
    </div>
  );
}

// ============================================================================
// THREAD HEAD
// ============================================================================
function ThreadHead({ conv, aiOn, onToggleAi, t }) {
  if (!conv) return null;
  return (
    <div className="thread-head">
      <div className="thread-left">
        <div className="avatar" style={{ width: 40, height: 40, background: conv.avatar.color, fontSize: 14 }}>
          {conv.avatar.initials}
        </div>
        <div>
          <div className="name">{conv.name}</div>
          <div className="status">{conv.lastTime}</div>
        </div>
      </div>
      <div className="thread-right">
        <button className={`ai-toggle ${aiOn ? 'on' : ''}`} onClick={onToggleAi} title={aiOn ? 'Disable AI' : 'Enable AI'}>
          <I.Sparkle /> {aiOn ? 'AI ON' : 'AI OFF'}
        </button>
        <button title="More options"><I.Dots /></button>
      </div>
    </div>
  );
}

// ============================================================================
// THREAD COLUMN
// ============================================================================
function ThreadColumn({ conv, aiOn, onToggleAi, t }) {
  const [draft, setDraft] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(true);
  const [messages, setMessages] = useState([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (!conv) return;

    const loadMessages = async () => {
      try {
        setLoadingMessages(true);
        
        const { data } = await apiCall(`/api/v2/conversation/${conv.id}/messages`);
        setMessages(data || []);
        
        setTimeout(() => {
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }, 100);
      } catch (error) {
        console.error('Failed to load messages:', error);
      } finally {
        setLoadingMessages(false);
      }
    };

    loadMessages();
  }, [conv?.id]);

  const handleSendMessage = async (text) => {
    if (!conv || !text.trim()) return;

    try {
      setSending(true);

      await apiCall('/api/v2/send-message', {
        method: 'POST',
        body: JSON.stringify({
          conversation_id: conv.id,
          text: text.trim()
        })
      });

      setDraft('');
      
      const { data } = await apiCall(`/api/v2/conversation/${conv.id}/messages`);
      setMessages(data || []);
    } catch (error) {
      console.error('Error sending message:', error);
      alert('Failed to send message: ' + error.message);
    } finally {
      setSending(false);
    }
  };

  const handleToggleAi = async () => {
    if (!conv) return;

    try {
      await apiCall(`/api/v2/conversation/${conv.id}/ai-toggle`, {
        method: 'POST',
        body: JSON.stringify({ enabled: !aiOn })
      });

      onToggleAi();
    } catch (error) {
      console.error('Error toggling AI:', error);
      alert('Failed to toggle AI: ' + error.message);
    }
  };

  if (!conv) {
    return <section className="thread-col"><div className="empty">{t.noConversation || 'Select a conversation'}</div></section>;
  }

  return (
    <section className="thread-col">
      <ThreadHead conv={conv} aiOn={aiOn} onToggleAi={handleToggleAi} t={t} />

      <div className="messages">
        {loadingMessages ? (
          <div className="empty">{t.loading || 'Loading messages...'}</div>
        ) : messages.length === 0 ? (
          <div className="empty">{t.noMessages || 'No messages yet'}</div>
        ) : (
          messages.map(m => <Message key={m.id} m={m} conv={conv} t={t} />)
        )}
        <div ref={messagesEndRef} />
      </div>

      {aiOn && (
        <div className="ai-banner">
          <I.Sparkle />
          <span><em>AI</em> is keeping this chat warm. Start typing to take over.</span>
        </div>
      )}

      {showSuggestions && conv.suggestions?.length > 0 && (
        <div className="suggest-row">
          <span className="label">{t.suggested}</span>
          {conv.suggestions.map((s, i) => (
            <button 
              key={i} 
              className="suggestion" 
              onClick={() => setDraft(s)}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="composer">
        <div className="composer-card">
          <textarea
            className="composer-input"
            placeholder={`${t.typing} ${conv.name.split(' ')[0]}…`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={sending}
            rows={1}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !sending) {
                e.preventDefault();
                if (draft.trim()) {
                  handleSendMessage(draft);
                }
              }
            }}
          />
          <div className="composer-bar">
            <button className="tool-btn" title="Attach" disabled={sending}>
              <I.Paperclip />
            </button>
            <button className="tool-btn" title="Photo" disabled={sending}>
              <I.Photo />
            </button>
            <button className="tool-btn" title="Voice" disabled={sending}>
              <I.Mic />
            </button>
            <button className="tool-btn" title="Emoji" disabled={sending}>
              <I.Smile />
            </button>
            <div className="grow" />
            <span style={{ fontSize: 11, color: 'var(--muted)', marginRight: 6 }}>
              {t.kbdHint}
            </span>
            <button 
              className={`send ${draft.trim() && !sending ? '' : 'disabled'}`}
              onClick={() => handleSendMessage(draft)}
              disabled={!draft.trim() || sending}
            >
              <I.Send /> {sending ? (t.sending || 'Sending...') : t.send}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

// ============================================================================
// DETAIL COLUMN
// ============================================================================
function DetailColumn({ conv, t }) {
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
        <h3>{t.stats}</h3>
        <div className="kpi-row">
          <div className="kpi">
            <div className="label">Orders</div>
            <div className="value">{conv.kpis.orders}</div>
            <div className="delta up">all paid</div>
          </div>
          <div className="kpi">
            <div className="label">Spent</div>
            <div className="value"><sup>$</sup>{conv.kpis.ltv}</div>
            <div className={`delta ${conv.kpis.conv.startsWith('+') ? 'up' : ''}`}>{conv.kpis.conv} this q.</div>
          </div>
        </div>
      </div>

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

// ============================================================================
// TOP BAR
// ============================================================================
function TopBar({ t, lang, setLang, theme, setTheme, conv, aiOn, onToggleAi }) {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" />
      </div>
      <div className="topbar-list">
        <span className="wordmark">{t.appName}<em>{t.appNameAccent}</em></span>
        <button className="acct-pill" title="Switch account" style={{ marginLeft: 'auto' }}>
          <span className="av">L</span>
          <span>Loomé</span>
          <I.Caret />
        </button>
      </div>
      <ThreadHead conv={conv} aiOn={aiOn} onToggleAi={onToggleAi} t={t} />
      <div className="topbar-right">
        <div className="lang">
          {['en', 'uz', 'ru'].map(l => (
            <button key={l} className={lang === l ? 'on' : ''} onClick={() => setLang(l)}>{l}</button>
          ))}
        </div>
        <button className="theme-btn" title="Theme" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
          {theme === 'dark' ? <I.Sun /> : <I.Moon />}
        </button>
        <button className="icon-btn" title="Notifications" style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8 }}>
          <I.Bell />
        </button>
        <button className="profile">
          <span className="av">A</span>
          <span>Aziz</span>
          <I.Caret />
        </button>
      </div>
    </header>
  );
}

// ============================================================================
// APP ROOT
// ============================================================================
const TWEAK_DEFAULTS = {
  theme: "light"
};

function App() {
  const [lang, setLang] = useState('en');
  const t = window.STRINGS[lang];

  const [conversations, setConversations] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const loadConversations = async () => {
      try {
        setLoading(true);
        const { data } = await apiCall('/api/v2/conversations');
        setConversations(data || []);
        
        if (data && data.length > 0) {
          setSelectedId(data[0].id);
        }
      } catch (err) {
        console.error('Failed to load conversations:', err);
        setError('Failed to load conversations: ' + err.message);
      } finally {
        setLoading(false);
      }
    };

    loadConversations();
  }, []);

  // Auto-refresh conversations
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const { data } = await apiCall('/api/v2/conversations');
        setConversations(data || []);
      } catch (err) {
        console.error('Failed to refresh conversations:', err);
      }
    }, 30000);

    return () => clearInterval(interval);
  }, []);

  const conv = conversations.find(c => c.id === selectedId);
  const aiOn = conv ? conv.aiOn : false;

  const [theme, setTheme] = useState(TWEAK_DEFAULTS.theme);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const toggleAi = () => {
    setConversations(cs => cs.map(c => c.id === selectedId ? { ...c, aiOn: !c.aiOn, needsHuman: c.aiOn ? c.needsHuman : false } : c));
  };

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: 'var(--bg)' }}>
      <p>{t?.loading || 'Loading...'}</p>
    </div>;
  }

  if (error) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: 'var(--bg)' }}>
      <p style={{ color: 'var(--warn)' }}>{error}</p>
    </div>;
  }

  return (
    <>
      <div className="app">
        <TopBar t={t} lang={lang} setLang={setLang} theme={theme} setTheme={setTheme}
                conv={conv} aiOn={aiOn} onToggleAi={toggleAi} />
        <Rail t={t} />
        <ListColumn conversations={conversations} selectedId={selectedId} onSelect={setSelectedId} t={t} />
        <ThreadColumn conv={conv} aiOn={aiOn} onToggleAi={toggleAi} t={t} />
        <DetailColumn conv={conv} t={t} />
      </div>

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

// Check for auth before rendering
const authToken = getAuthToken();

if (!authToken) {
  ReactDOM.createRoot(document.getElementById('root')).render(<LoginPage />);
} else {
  ReactDOM.createRoot(document.getElementById('root')).render(<App />);
}
