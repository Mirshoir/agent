import React, { useState, useEffect } from 'react';
import { apiClient } from '../api';
import { Save, Loader } from 'lucide-react';

function Settings() {
  const [businesses, setBusinesses] = useState([]);
  const [selectedBusiness, setSelectedBusiness] = useState(null);
  const [settings, setSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    loadBusinesses();
  }, []);

  useEffect(() => {
    if (selectedBusiness) {
      setSettings({
        business_name: selectedBusiness.business_name || '',
        business_type: selectedBusiness.business_type || 'ecommerce',
        language: selectedBusiness.language || 'uz',
        bot_enabled: selectedBusiness.bot_enabled || false,
        ai_tokens: selectedBusiness.ai_tokens || 2000,
        ai_temperature: selectedBusiness.ai_temperature || 0.7,
        catalog_link: selectedBusiness.catalog_link || '',
        sales_phone: selectedBusiness.sales_phone || '',
      });
    }
  }, [selectedBusiness]);

  const loadBusinesses = async () => {
    try {
      setLoading(true);
      const response = await apiClient.getBusinesses();
      if (response.status === 'ok') {
        setBusinesses(response.data);
        if (response.data.length > 0) {
          setSelectedBusiness(response.data[0]);
        }
      }
    } catch (err) {
      setMessage(`Error: ${err.message || 'Failed to load businesses'}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!selectedBusiness) return;

    try {
      setSaving(true);
      const response = await apiClient.updateBusinessSettings(
        selectedBusiness.id,
        settings
      );
      
      if (response.status === 'ok') {
        setMessage('✅ Settings saved successfully!');
        setTimeout(() => setMessage(''), 3000);
      }
    } catch (err) {
      setMessage(`❌ Error: ${err.message || 'Failed to save settings'}`);
    } finally {
      setSaving(false);
    }
  };

  const handleChange = (field, value) => {
    setSettings(prev => ({
      ...prev,
      [field]: value
    }));
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center h-full">
        <div className="text-center">
          <Loader className="w-8 h-8 animate-spin mx-auto mb-4 text-indigo-600" />
          <p className="text-gray-600">Loading settings...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-4xl">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-4xl font-bold text-gray-900 mb-2">⚙️ Settings</h1>
        <p className="text-gray-600">Configure your business accounts</p>
      </div>

      {/* Message */}
      {message && (
        <div className={`mb-6 p-4 rounded-lg ${
          message.startsWith('✅') 
            ? 'bg-green-50 text-green-700 border border-green-200'
            : 'bg-red-50 text-red-700 border border-red-200'
        }`}>
          {message}
        </div>
      )}

      {/* Business Selector */}
      <div className="mb-8">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Select Business Account
        </label>
        <select
          value={selectedBusiness?.id || ''}
          onChange={(e) => {
            const biz = businesses.find(b => b.id === e.target.value);
            setSelectedBusiness(biz);
          }}
          className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          {businesses.map(b => (
            <option key={b.id} value={b.id}>
              {b.business_name || `Business ${b.id.slice(0, 8)}`}
            </option>
          ))}
        </select>
      </div>

      {selectedBusiness && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 space-y-6">
          {/* Business Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              📝 Business Name
            </label>
            <input
              type="text"
              value={settings.business_name}
              onChange={(e) => handleChange('business_name', e.target.value)}
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="My Business"
            />
          </div>

          {/* Business Type */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                🏪 Business Type
              </label>
              <select
                value={settings.business_type}
                onChange={(e) => handleChange('business_type', e.target.value)}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="ecommerce">E-Commerce</option>
                <option value="service">Service</option>
                <option value="restaurant">Restaurant</option>
                <option value="other">Other</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                🌐 Language
              </label>
              <select
                value={settings.language}
                onChange={(e) => handleChange('language', e.target.value)}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="uz">Ўзбек</option>
                <option value="ru">Русский</option>
                <option value="en">English</option>
              </select>
            </div>
          </div>

          {/* AI Settings */}
          <div className="pt-6 border-t border-gray-200">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">🤖 AI Settings</h3>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Auto-Reply Enabled
                </label>
                <div className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={settings.bot_enabled}
                    onChange={(e) => handleChange('bot_enabled', e.target.checked)}
                    className="w-5 h-5 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500 cursor-pointer"
                  />
                  <span className="text-sm text-gray-600">
                    {settings.bot_enabled ? '✅ Enabled' : '⭕ Disabled'}
                  </span>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Max Tokens per Response
                </label>
                <input
                  type="number"
                  value={settings.ai_tokens}
                  onChange={(e) => handleChange('ai_tokens', parseInt(e.target.value))}
                  min="100"
                  max="4000"
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2 mt-4">
                Temperature (Creativity): {settings.ai_temperature}
              </label>
              <input
                type="range"
                value={settings.ai_temperature}
                onChange={(e) => handleChange('ai_temperature', parseFloat(e.target.value))}
                min="0"
                max="1"
                step="0.1"
                className="w-full"
              />
              <p className="text-xs text-gray-500 mt-1">
                Lower = More focused | Higher = More creative
              </p>
            </div>
          </div>

          {/* Contact Information */}
          <div className="pt-6 border-t border-gray-200">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">📞 Contact Information</h3>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Sales Phone
                </label>
                <input
                  type="text"
                  value={settings.sales_phone}
                  onChange={(e) => handleChange('sales_phone', e.target.value)}
                  placeholder="+998 XX XXX XX XX"
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Catalog Link
                </label>
                <input
                  type="url"
                  value={settings.catalog_link}
                  onChange={(e) => handleChange('catalog_link', e.target.value)}
                  placeholder="https://..."
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </div>
          </div>

          {/* Save Button */}
          <div className="pt-6 border-t border-gray-200">
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center justify-center space-x-2 px-6 py-3 bg-gradient-to-r from-indigo-500 to-purple-600 text-white font-semibold rounded-lg hover:shadow-lg transform hover:-translate-y-0.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? (
                <>
                  <Loader className="w-5 h-5 animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <>
                  <Save className="w-5 h-5" />
                  <span>Save Settings</span>
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default Settings;
