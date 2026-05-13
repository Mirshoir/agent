import React, { useState, useEffect, useRef } from 'react';
import { apiClient } from '../api';
import ConversationList from '../components/ConversationList';
import ChatView from '../components/ChatView';
import { MessageCircle, Search } from 'lucide-react';

function Chat() {
  const [conversations, setConversations] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [platform, setPlatform] = useState('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [messageLoading, setMessageLoading] = useState(false);
  const [error, setError] = useState('');

  // Load conversations
  useEffect(() => {
    loadConversations();
    const interval = setInterval(loadConversations, 5000); // Refresh every 5s
    return () => clearInterval(interval);
  }, [platform, search]);

  // Load messages when conversation changes
  useEffect(() => {
    if (selectedConversation) {
      loadMessages();
      const interval = setInterval(loadMessages, 3000); // Refresh every 3s
      return () => clearInterval(interval);
    }
  }, [selectedConversation]);

  const loadConversations = async () => {
    try {
      setLoading(true);
      const response = await apiClient.getConversations(platform, search);
      if (response.status === 'ok') {
        setConversations(response.data);
      }
    } catch (err) {
      setError(err.message || 'Failed to load conversations');
    } finally {
      setLoading(false);
    }
  };

  const loadMessages = async () => {
    if (!selectedConversation) return;
    
    try {
      setMessageLoading(true);
      const response = await apiClient.getConversation(selectedConversation.id);
      if (response.status === 'ok') {
        setMessages(response.data);
      }
    } catch (err) {
      console.error('Failed to load messages:', err);
    } finally {
      setMessageLoading(false);
    }
  };

  const handleSendMessage = async (text) => {
    if (!selectedConversation || !text.trim()) return;

    try {
      const response = await apiClient.sendMessage(
        selectedConversation.id,
        text,
        selectedConversation.business_id
      );
      
      if (response.status === 'ok') {
        loadMessages();
      }
    } catch (err) {
      console.error('Failed to send message:', err);
    }
  };

  const handleSendFile = async (file, caption, mediaType) => {
    if (!selectedConversation) return;

    try {
      const reader = new FileReader();
      reader.onload = async (e) => {
        const base64 = e.target.result.split(',')[1];
        const response = await apiClient.sendFile(
          selectedConversation.id,
          caption,
          mediaType,
          base64,
          file.name,
          selectedConversation.business_id
        );
        
        if (response.status === 'ok') {
          loadMessages();
        }
      };
      reader.readAsDataURL(file);
    } catch (err) {
      console.error('Failed to send file:', err);
    }
  };

  const handleSendVoice = async (file) => {
    if (!selectedConversation) return;

    try {
      const reader = new FileReader();
      reader.onload = async (e) => {
        const base64 = e.target.result.split(',')[1];
        const response = await apiClient.sendVoice(
          selectedConversation.customer_id,
          base64,
          file.name,
          selectedConversation.chat_id
        );
        
        if (response.status === 'ok') {
          loadMessages();
        }
      };
      reader.readAsDataURL(file);
    } catch (err) {
      console.error('Failed to send voice:', err);
    }
  };

  return (
    <div className="h-full flex">
      {/* Conversations Sidebar */}
      <div className="w-96 bg-white border-r border-gray-200 flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-200">
          <h2 className="text-xl font-bold text-gray-900 mb-4">💬 Conversations</h2>
          
          {/* Filters */}
          <div className="space-y-3">
            {/* Platform Filter */}
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="all">All Platforms</option>
              <option value="instagram">Instagram</option>
              <option value="telegram">Telegram</option>
            </select>

            {/* Search */}
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-3 text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search conversations..."
                className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>
        </div>

        {/* Conversations List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="p-4 text-center text-gray-500">
              <p>Loading conversations...</p>
            </div>
          ) : conversations.length === 0 ? (
            <div className="p-4 text-center text-gray-500">
              <MessageCircle className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No conversations yet</p>
            </div>
          ) : (
            <ConversationList
              conversations={conversations}
              selectedId={selectedConversation?.id}
              onSelect={setSelectedConversation}
            />
          )}
        </div>
      </div>

      {/* Chat View */}
      <div className="flex-1 bg-white flex flex-col">
        {selectedConversation ? (
          <ChatView
            conversation={selectedConversation}
            messages={messages}
            loading={messageLoading}
            onSendMessage={handleSendMessage}
            onSendFile={handleSendFile}
            onSendVoice={handleSendVoice}
          />
        ) : (
          <div className="flex items-center justify-center h-full bg-gray-50">
            <div className="text-center">
              <MessageCircle className="w-12 h-12 mx-auto mb-4 text-gray-300" />
              <p className="text-gray-500 text-lg">Select a conversation to start</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default Chat;
