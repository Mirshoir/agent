import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: `${API_BASE}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add auth token to requests if available
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  const secret = localStorage.getItem('dashboard_secret');
  if (secret) {
    config.headers['x-dashboard-secret'] = secret;
  }
  return config;
});

// Handle responses
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token');
      window.location.href = '/login';
    }
    return Promise.reject(error.response?.data || error.message);
  }
);

export const apiClient = {
  // Auth
  login: (email, password) => api.post('/auth/login', { email, password }),
  
  // Health
  health: () => api.get('/health'),
  
  // Businesses
  getBusinesses: () => api.get('/businesses'),
  getBusiness: (id) => api.get(`/business/${id}`),
  updateBusinessSettings: (id, settings) => 
    api.post(`/business-settings?business_id=${id}`, { settings }),
  
  // Conversations
  getConversations: (platform = 'all', search = '') =>
    api.get(`/conversations?platform=${platform}&search=${encodeURIComponent(search)}`),
  getConversation: (conversationId, limit = 250) =>
    api.get(`/conversation/${conversationId}?limit=${limit}`),
  
  // Messages
  sendMessage: (conversationId, text, businessId) =>
    api.post(`/send-message?conversation_id=${conversationId}&text=${encodeURIComponent(text)}&business_id=${businessId}`),
  
  sendFile: (conversationId, caption, mediaType, fileData, filename, businessId) =>
    api.post(`/send-file?conversation_id=${conversationId}&caption=${encodeURIComponent(caption)}&media_type=${mediaType}&filename=${filename}&business_id=${businessId}`, 
      { file_data: fileData }),
  
  sendVoice: (customerId, fileData, filename, chatId = '') =>
    api.post(`/send-voice?customer_id=${customerId}&filename=${filename}&chat_id=${chatId}`,
      { file_data: fileData }),
  
  // Chat AI Toggle
  toggleChatAI: (businessId, platform, channel, customerId, enabled) =>
    api.post(`/chat-ai-toggle?business_id=${businessId}&platform=${platform}&channel=${channel}&customer_id=${customerId}&enabled=${enabled}`),
  
  // Statistics
  getStats: () => api.get('/stats'),
};

export default api;
