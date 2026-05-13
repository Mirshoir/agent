import React, { useState, useEffect } from 'react';
import { apiClient } from '../api';
import StatCard from '../components/StatCard';
import { BarChart3, MessageCircle, Users, Activity } from 'lucide-react';

function Overview() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    loadStats();
  }, []);

  const loadStats = async () => {
    try {
      setLoading(true);
      const response = await apiClient.getStats();
      if (response.status === 'ok') {
        setStats(response.data);
      }
    } catch (err) {
      setError(err.message || 'Failed to load statistics');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center h-full">
        <div className="text-center">
          <div className="text-4xl mb-4">📊</div>
          <p className="text-gray-600">Loading statistics...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-4xl font-bold text-gray-900 mb-2">📈 Dashboard</h1>
        <p className="text-gray-600">Overview of your sales channels</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <StatCard
          icon={<Users className="w-8 h-8" />}
          title="Sales Accounts"
          value={stats?.total_accounts || 0}
          color="bg-blue-500"
        />
        <StatCard
          icon={<Activity className="w-8 h-8" />}
          title="Active Auto-Reply"
          value={stats?.active_accounts || 0}
          color="bg-green-500"
        />
        <StatCard
          icon={<MessageCircle className="w-8 h-8" />}
          title="Instagram Messages"
          value={(stats?.instagram_messages || 0).toLocaleString()}
          color="bg-pink-500"
        />
        <StatCard
          icon={<MessageCircle className="w-8 h-8" />}
          title="Telegram Messages"
          value={(stats?.telegram_messages || 0).toLocaleString()}
          color="bg-sky-500"
        />
      </div>

      {/* Recent Activity */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-xl font-bold text-gray-900 mb-4">📊 Quick Stats</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-gray-600 mb-1">Total Messages</p>
            <p className="text-2xl font-bold text-gray-900">
              {((stats?.instagram_messages || 0) + (stats?.telegram_messages || 0)).toLocaleString()}
            </p>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-gray-600 mb-1">Accounts Configured</p>
            <p className="text-2xl font-bold text-gray-900">{stats?.total_accounts || 0}</p>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-gray-600 mb-1">Instagram Active</p>
            <p className="text-2xl font-bold text-pink-600">{(stats?.instagram_messages || 0).toLocaleString()}</p>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <p className="text-gray-600 mb-1">Telegram Active</p>
            <p className="text-2xl font-bold text-sky-600">{(stats?.telegram_messages || 0).toLocaleString()}</p>
          </div>
        </div>
      </div>

      {/* Help Section */}
      <div className="mt-8 bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-6 border border-indigo-200">
        <h3 className="text-lg font-semibold text-gray-900 mb-2">💡 Getting Started</h3>
        <ul className="space-y-2 text-sm text-gray-700">
          <li>✅ Go to Chat to view and respond to customer messages</li>
          <li>✅ Visit Settings to configure your business details</li>
          <li>✅ Send photos, videos, and voice messages directly</li>
          <li>✅ Toggle AI auto-replies per conversation</li>
        </ul>
      </div>
    </div>
  );
}

export default Overview;
