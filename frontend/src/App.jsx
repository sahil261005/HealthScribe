import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import Dashboard from './components/Dashboard';
import UploadModal from './components/UploadModal';
import ChatInterface from './components/ChatInterface';
import AuthPage from './components/AuthPage';
import SharedReport from './components/SharedReport';
import './App.css';

function AppContent() {
    const { user, isAuthenticated, isLoading, logout } = useAuth();
    const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
    const [dashboardRefreshKey, setDashboardRefreshKey] = useState(0);
    const [currentView, setCurrentView] = useState('home');

    // bump the key to force dashboard to refetch after upload
    const handleUploadSuccess = () => {
        setDashboardRefreshKey(previousKey => previousKey + 1);
    };

    const openUploadModal = () => setIsUploadModalOpen(true);
    const closeUploadModal = () => setIsUploadModalOpen(false);

    if (isLoading) {
        return (
            <div className="loading-screen">
                <div className="loading-content">
                    <p className="loading-text">Loading HealthScribe...</p>
                </div>
            </div>
        );
    }

    if (!isAuthenticated) {
        return <AuthPage />;
    }

    return (
        <div className="app-screen">
            <nav className="navbar">
                <h1 className="brand-title" onClick={() => setCurrentView('home')}>HealthScribe</h1>
                
                <div className="nav-actions">
                    <div className="nav-tabs">
                        <button 
                            className={`nav-tab ${currentView === 'home' ? 'nav-tab-active' : ''}`}
                            onClick={() => setCurrentView('home')}
                        >
                            Home
                        </button>
                        <button 
                            className={`nav-tab ${currentView === 'dashboard' ? 'nav-tab-active' : ''}`}
                            onClick={() => setCurrentView('dashboard')}
                        >
                            Dashboard
                        </button>
                    </div>

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
                        Logout
                    </button>
                </div>
            </nav>

            <main className="main-content">
                {currentView === 'home' ? (
                    <div className="home-welcome">
                        <div className="home-hero">
                            <div className="home-badge">AI-Powered Health Platform</div>
                            <h2 className="home-tagline">
                                Your prescriptions, <span className="home-highlight">digitized & searchable.</span>
                            </h2>
                            <p className="home-description">
                                Snap a photo of any handwritten prescription. Our AI extracts medicines, 
                                dosages, symptoms, and vitals — then lets you search your entire medical 
                                history with a smart chatbot.
                            </p>
                            <div className="home-actions">
                                <button onClick={openUploadModal} className="btn-scan-now">
                                    Scan Prescription
                                </button>
                                <button onClick={() => setCurrentView('dashboard')} className="btn-view-dashboard">
                                    View Dashboard
                                </button>
                            </div>
                        </div>

                        <div className="home-features-grid">
                            <div className="home-feature-card">
                                <div className="home-feature-number">01</div>
                                <h4 className="home-feature-title">Snap & Extract</h4>
                                <p className="home-feature-text">
                                    Upload a prescription photo. AI reads handwritten text and extracts 
                                    structured medical data in seconds.
                                </p>
                            </div>
                            <div className="home-feature-card">
                                <div className="home-feature-number">02</div>
                                <h4 className="home-feature-title">Ask AI Assistant</h4>
                                <p className="home-feature-text">
                                    Chat with your health data. Ask questions like "What was my last 
                                    BP reading?" and get instant answers.
                                </p>
                            </div>
                            <div className="home-feature-card">
                                <div className="home-feature-number">03</div>
                                <h4 className="home-feature-title">Track & Compare</h4>
                                <p className="home-feature-text">
                                    Visualize vitals over time, spot conflicting prescriptions across 
                                    doctors, and share reports via QR code.
                                </p>
                            </div>
                        </div>
                    </div>
                ) : (
                    <Dashboard key={dashboardRefreshKey} onUploadClick={openUploadModal} />
                )}
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
    // check if someone is visiting via a share link
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');

    if (token) {
        return <SharedReport token={token} />;
    }

    return (
        <AuthProvider>
            <AppContent />
        </AuthProvider>
    );
}

export default App;
