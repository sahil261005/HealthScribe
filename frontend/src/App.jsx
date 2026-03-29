import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import Dashboard from './components/Dashboard';
import UploadModal from './components/UploadModal';
import ChatInterface from './components/ChatInterface';
import AuthPage from './components/AuthPage';
import { LogOut, Loader2 } from 'lucide-react';
import './App.css';

function AppContent() {
    const { user, isAuthenticated, isLoading, logout } = useAuth();
    const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
    const [dashboardRefreshKey, setDashboardRefreshKey] = useState(0);

    // when a record is uploaded, bump the key so dashboard refetches data
    const handleUploadSuccess = () => {
        setDashboardRefreshKey(previousKey => previousKey + 1);
    };

    const openUploadModal = () => setIsUploadModalOpen(true);
    const closeUploadModal = () => setIsUploadModalOpen(false);

    // show spinner while checking if user is already logged in
    if (isLoading) {
        return (
            <div className="loading-screen">
                <div className="loading-content">
                    <Loader2 size={40} />
                    <p style={{ marginTop: '12px', fontSize: '15px' }}>Loading HealthScribe...</p>
                </div>
            </div>
        );
    }

    // not logged in, show auth page
    if (!isAuthenticated) {
        return <AuthPage />;
    }

    return (
        <div className="app-screen">
            <nav className="navbar">
                <h1 className="brand-title">HealthScribe</h1>
                
                <div className="nav-actions">
                    <div className="user-profile">
                        <div className="user-avatar">
                            {user?.username?.charAt(0).toUpperCase() || 'U'}
                        </div>
                        <span className="user-name">{user?.username}</span>
                    </div>
                    
                    <button onClick={openUploadModal} className="btn-upload">
                        + Upload Record
                    </button>
                    
                    <button onClick={logout} className="btn-logout" title="Logout">
                        <LogOut size={18} />
                        <span>Logout</span>
                    </button>
                </div>
            </nav>

            <main className="main-content">
                <Dashboard key={dashboardRefreshKey} />
            </main>

            <UploadModal 
                isOpen={isUploadModalOpen} 
                onClose={closeUploadModal} 
                onUploadSuccess={handleUploadSuccess} 
            />
            
            <ChatInterface />
        </div>
    );
}

function App() {
    return (
        <AuthProvider>
            <AppContent />
        </AuthProvider>
    );
}

export default App;
