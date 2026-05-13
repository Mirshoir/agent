import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { apiClient } from './api';
import Navbar from './components/Navbar';
import Sidebar from './components/Sidebar';
import Login from './pages/Login';
import Overview from './pages/Overview';
import Chat from './pages/Chat';
import Settings from './pages/Settings';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    // Check authentication status
    const token = localStorage.getItem('auth_token');
    const storedUser = localStorage.getItem('user');
    
    if (token && storedUser) {
      setIsAuthenticated(true);
      setUser(JSON.parse(storedUser));
    }
    
    setLoading(false);
  }, []);

  const handleLogin = (email, userData, token) => {
    localStorage.setItem('auth_token', token);
    localStorage.setItem('user', JSON.stringify(userData));
    setUser(userData);
    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user');
    setUser(null);
    setIsAuthenticated(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gradient-to-br from-indigo-500 to-purple-600">
        <div className="text-white text-center">
          <div className="text-4xl mb-4">💬</div>
          <h1 className="text-3xl font-bold mb-2">Milana Premium</h1>
          <p className="text-lg opacity-90">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Login onLogin={handleLogin} />;
  }

  return (
    <Router>
      <div className="flex h-screen bg-gradient-to-br from-slate-50 to-slate-100">
        {/* Sidebar */}
        <Sidebar 
          open={sidebarOpen} 
          onToggle={() => setSidebarOpen(!sidebarOpen)}
          user={user}
          onLogout={handleLogout}
        />
        
        {/* Main Content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Navbar */}
          <Navbar 
            onSidebarToggle={() => setSidebarOpen(!sidebarOpen)}
            user={user}
          />
          
          {/* Page Content */}
          <main className="flex-1 overflow-auto">
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/chat" element={<Chat />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
        </div>
      </div>
    </Router>
  );
}

export default App;
