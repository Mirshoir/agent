// Navbar.jsx
import React from 'react';
import { Menu, LogOut, User } from 'lucide-react';

export default function Navbar({ onSidebarToggle, user }) {
  return (
    <nav className="bg-white border-b border-gray-200 shadow-sm">
      <div className="px-6 py-4 flex items-center justify-between">
        <button
          onClick={onSidebarToggle}
          className="p-2 hover:bg-gray-100 rounded-lg transition"
        >
          <Menu className="w-6 h-6 text-gray-600" />
        </button>
        
        <div className="flex items-center space-x-4">
          <div className="text-right hidden sm:block">
            <p className="text-sm font-medium text-gray-900">{user?.email}</p>
            <p className="text-xs text-gray-500">
              {user?.is_admin ? '👑 Admin' : '👤 Manager'}
            </p>
          </div>
          <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center text-white font-bold">
            {user?.email?.[0].toUpperCase()}
          </div>
        </div>
      </div>
    </nav>
  );
}

// Sidebar.jsx
export function Sidebar({ open, onToggle, user, onLogout }) {
  return (
    <>
      {/* Overlay */}
      {open && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-40 lg:hidden"
          onClick={onToggle}
        />
      )}

      {/* Sidebar */}
      <div className={`fixed lg:static inset-y-0 left-0 z-50 w-64 bg-white border-r border-gray-200 transform transition-transform duration-300 ${
        open ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
      }`}>
        <div className="h-full flex flex-col">
          {/* Logo */}
          <div className="p-6 border-b border-gray-200">
            <h1 className="text-2xl font-bold bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent">
              💬 Milana
            </h1>
            <p className="text-xs text-gray-500 mt-1">Premium Sales Dashboard</p>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-4 py-6 space-y-2">
            {[
              { icon: '📈', label: 'Overview', path: '/' },
              { icon: '💬', label: 'Conversations', path: '/chat' },
              { icon: '⚙️', label: 'Settings', path: '/settings' },
            ].map(item => (
              <a
                key={item.path}
                href={item.path}
                className="flex items-center space-x-3 px-4 py-3 text-gray-700 hover:bg-indigo-50 hover:text-indigo-600 rounded-lg transition"
              >
                <span>{item.icon}</span>
                <span>{item.label}</span>
              </a>
            ))}
          </nav>

          {/* Footer */}
          <div className="p-4 border-t border-gray-200">
            <button
              onClick={onLogout}
              className="w-full flex items-center justify-center space-x-2 px-4 py-3 text-red-600 hover:bg-red-50 rounded-lg transition text-sm font-medium"
            >
              <LogOut className="w-4 h-4" />
              <span>Logout</span>
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

// ConversationList.jsx
export function ConversationList({ conversations, selectedId, onSelect }) {
  return (
    <div className="space-y-1">
      {conversations.map(conv => (
        <button
          key={conv.id}
          onClick={() => onSelect(conv)}
          className={`w-full text-left px-4 py-3 rounded-lg transition ${
            selectedId === conv.id
              ? 'bg-indigo-50 border-l-4 border-indigo-600'
              : 'hover:bg-gray-50 border-l-4 border-transparent'
          }`}
        >
          <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0">
              <p className="font-medium text-gray-900 text-sm truncate">
                {conv.customer_name}
              </p>
              <p className="text-xs text-gray-500 truncate">
                {conv.platform} • {conv.channel}
              </p>
              <p className="text-xs text-gray-600 mt-1 line-clamp-2">
                {conv.last_message || 'No messages yet'}
              </p>
            </div>
            {conv.unread_count > 0 && (
              <span className="ml-2 px-2 py-1 bg-red-500 text-white text-xs rounded-full font-semibold">
                {conv.unread_count}
              </span>
            )}
          </div>
        </button>
      ))}
    </div>
  );
}

// ChatView.jsx
export function ChatView({ conversation, messages, loading, onSendMessage, onSendFile, onSendVoice }) {
  const [text, setText] = React.useState('');
  const [tab, setTab] = React.useState('text');
  const messagesEndRef = React.useRef(null);

  React.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (text.trim()) {
      onSendMessage(text);
      setText('');
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white">
        <h3 className="font-semibold text-gray-900">{conversation.customer_name}</h3>
        <p className="text-xs text-gray-500">
          {conversation.platform} • {conversation.total_messages} messages
        </p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {loading ? (
          <div className="text-center text-gray-500">Loading messages...</div>
        ) : messages.length === 0 ? (
          <div className="text-center text-gray-500">No messages yet</div>
        ) : (
          messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex ${msg.direction === 'outbound' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-xs lg:max-w-md px-4 py-2 rounded-lg ${
                  msg.direction === 'outbound'
                    ? 'bg-indigo-600 text-white rounded-br-none'
                    : 'bg-gray-100 text-gray-900 rounded-bl-none'
                }`}
              >
                {msg.media_type && msg.media_url && (
                  <div className="mb-2">
                    {msg.media_type === 'photo' && (
                      <img src={msg.media_url} alt="photo" className="max-w-xs rounded" />
                    )}
                    {msg.media_type === 'video' && (
                      <video src={msg.media_url} controls className="max-w-xs rounded" />
                    )}
                    {msg.media_type === 'voice' && (
                      <audio src={msg.media_url} controls className="w-full" />
                    )}
                  </div>
                )}
                {msg.content && <p className="text-sm">{msg.content}</p>}
                <p className={`text-xs mt-1 ${
                  msg.direction === 'outbound' ? 'text-indigo-100' : 'text-gray-500'
                }`}>
                  {new Date(msg.created_at).toLocaleTimeString()}
                </p>
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 bg-white p-4">
        <div className="flex space-x-2 mb-3 border-b border-gray-200">
          <button
            onClick={() => setTab('text')}
            className={`px-3 py-2 text-sm font-medium ${
              tab === 'text'
                ? 'border-b-2 border-indigo-600 text-indigo-600'
                : 'text-gray-600'
            }`}
          >
            💬 Text
          </button>
          <button
            onClick={() => setTab('file')}
            className={`px-3 py-2 text-sm font-medium ${
              tab === 'file'
                ? 'border-b-2 border-indigo-600 text-indigo-600'
                : 'text-gray-600'
            }`}
          >
            📎 Files
          </button>
          <button
            onClick={() => setTab('voice')}
            className={`px-3 py-2 text-sm font-medium ${
              tab === 'voice'
                ? 'border-b-2 border-indigo-600 text-indigo-600'
                : 'text-gray-600'
            }`}
          >
            🎤 Voice
          </button>
        </div>

        {tab === 'text' && (
          <div className="flex space-x-2">
            <input
              type="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && handleSend()}
              placeholder="Type message..."
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <button
              onClick={handleSend}
              className="px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition font-medium"
            >
              Send
            </button>
          </div>
        )}

        {tab === 'file' && (
          <div className="space-y-2">
            <input type="file" accept="image/*,video/*" onChange={(e) => {
              if (e.target.files?.[0]) {
                const type = e.target.files[0].type.startsWith('image') ? 'photo' : 'video';
                onSendFile(e.target.files[0], 'File', type);
              }
            }} className="w-full" />
          </div>
        )}

        {tab === 'voice' && (
          <div className="space-y-2">
            <input type="file" accept="audio/*" onChange={(e) => {
              if (e.target.files?.[0]) {
                onSendVoice(e.target.files[0]);
              }
            }} className="w-full" />
          </div>
        )}
      </div>
    </div>
  );
}

// StatCard.jsx
export function StatCard({ icon, title, value, color }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className={`w-12 h-12 rounded-lg ${color} text-white flex items-center justify-center mb-4`}>
        {icon}
      </div>
      <p className="text-gray-600 text-sm font-medium mb-1">{title}</p>
      <p className="text-3xl font-bold text-gray-900">{value}</p>
    </div>
  );
}

export default Navbar;
