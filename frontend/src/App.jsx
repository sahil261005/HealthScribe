import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import Dashboard from './components/Dashboard';
import UploadModal from './components/UploadModal';
import ChatInterface from './components/ChatInterface';
import AuthPage from './components/AuthPage';
import SharedReport from './components/SharedReport';
import TypewriterText from './components/TypewriterText';
import './App.css';

function AppContent() {
    const { user, isAuthenticated, isLoading, logout } = useAuth();
    const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
    const [dashboardRefreshKey, setDashboardRefreshKey] = useState(0);
    const [currentView, setCurrentView] = useState('home');

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
        <div className="min-h-screen flex flex-col bg-background text-on-background">
            {/* ── Top Navigation Bar ── */}
            <header className="bg-surface-container-lowest border-b border-outline-variant shadow-sm sticky top-0 z-50 w-full">
                <div className="relative flex justify-between items-center w-full h-16 px-margin-mobile md:px-margin-desktop max-w-[1440px] mx-auto">
                    {/* Brand */}
                    <button
                        onClick={() => setCurrentView('home')}
                        className="font-headline-md text-headline-md font-bold text-on-tertiary-container flex items-center gap-2 hover:opacity-80 transition-opacity"
                    >
                        HealthScribe
                    </button>

                    {/* Desktop Nav Tabs — absolutely centered so they stay in the middle regardless of side widths */}
                    <nav className="hidden md:flex absolute left-1/2 -translate-x-1/2 items-center bg-surface-container rounded-lg p-1 gap-1 border border-outline-variant/30">
                        <button
                            onClick={() => setCurrentView('home')}
                            className={`font-label-md text-label-md px-4 py-1.5 rounded-md transition-all duration-200 ${
                                currentView === 'home'
                                    ? 'text-on-tertiary-container font-semibold bg-surface-container-lowest shadow-sm'
                                    : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-low'
                            }`}
                        >
                            Home
                        </button>
                        <button
                            onClick={() => setCurrentView('dashboard')}
                            className={`font-label-md text-label-md px-4 py-1.5 rounded-md transition-all duration-200 ${
                                currentView === 'dashboard'
                                    ? 'text-on-tertiary-container font-semibold bg-surface-container-lowest shadow-sm'
                                    : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-low'
                            }`}
                        >
                            Dashboard
                        </button>
                    </nav>

                    {/* Actions */}
                    <div className="flex items-center gap-sm">
                        <button
                            onClick={openUploadModal}
                            className="hidden md:flex items-center gap-2 bg-on-tertiary-container text-white px-4 py-2 rounded-lg font-label-md text-label-md cursor-pointer hover:opacity-90 transition-opacity"
                        >
                            <span className="material-symbols-outlined" style={{fontSize: '18px'}}>add</span>
                            <span>Upload Record</span>
                        </button>
                        <div className="w-8 h-8 rounded-full bg-on-tertiary-container text-white flex items-center justify-center font-bold font-label-md text-label-md shadow-sm">
                            {user?.username?.charAt(0).toUpperCase() || 'U'}
                        </div>
                        <span className="text-on-surface-variant font-label-md text-label-md hidden md:block text-sm">
                            {user?.username}
                        </span>
                        <button
                            onClick={logout}
                            className="text-on-surface-variant hover:text-on-surface font-label-md text-label-md hidden md:block transition-colors duration-200 ml-1"
                        >
                            Logout
                        </button>
                    </div>
                </div>
            </header>

            {/* ── Main Content ── */}
            <main className="flex-grow flex flex-col items-center w-full max-w-[1440px] mx-auto px-margin-mobile md:px-margin-desktop py-xl gap-xl md:gap-[80px]">
                {currentView === 'home' ? (
                    <>
                        {/* ── Hero Section ── */}
                        <section className="w-full flex flex-col items-center text-center max-w-3xl mx-auto pt-lg md:pt-xl">
                            <h1 className="font-display-lg text-display-lg text-on-surface mb-md">
                                Your prescriptions,{' '}
                                <br className="hidden md:block" />
                                <span className="text-on-tertiary-container">
                                    <TypewriterText />
                                </span>
                            </h1>
                            <p className="font-body-lg text-body-lg text-on-surface-variant mb-lg max-w-2xl">
                                HealthScribe turns every handwritten prescription into structured, actionable health data. Chat with your history, track vitals, and share records securely.
                            </p>
                            <div className="flex flex-col sm:flex-row items-center gap-sm md:gap-md w-full sm:w-auto">
                                <button
                                    onClick={openUploadModal}
                                    className="w-full sm:w-auto bg-on-tertiary-container text-white px-8 py-3 rounded-lg font-label-md text-label-md hover:opacity-90 transition-all shadow-sm flex items-center justify-center gap-2"
                                >
                                    <span className="material-symbols-outlined text-base">document_scanner</span>
                                    Scan Prescription
                                </button>
                                <button
                                    onClick={() => setCurrentView('dashboard')}
                                    className="w-full sm:w-auto bg-surface-container-lowest text-on-tertiary-container border border-on-tertiary-container px-8 py-3 rounded-lg font-label-md text-label-md hover:bg-surface-container-low transition-all flex items-center justify-center gap-2"
                                >
                                    <span className="material-symbols-outlined text-base">dashboard</span>
                                    Go to Dashboard
                                </button>
                            </div>
                        </section>

                        {/* ── Hero Bento Visual Grid ── */}
                        <section className="w-full max-w-5xl mx-auto rounded-xl border border-outline-variant/50 bg-surface-container-lowest shadow-sm overflow-hidden flex flex-col md:flex-row items-stretch min-h-[400px]">
                            {/* Left: Abstract Prescription Card */}
                            <div className="w-full md:w-1/2 p-md md:p-lg bg-surface-bright flex flex-col justify-center items-center border-b md:border-b-0 md:border-r border-outline-variant/30 relative">
                                <div
                                    className="absolute inset-0 opacity-20"
                                    style={{ backgroundImage: "radial-gradient(circle at 2px 2px, #76777d 1px, transparent 0)", backgroundSize: "24px 24px" }}
                                />
                                <div className="relative z-10 w-full max-w-xs aspect-[3/4] bg-white rounded-lg border border-outline-variant shadow-sm p-4 flex flex-col transform -rotate-2 transition-transform hover:rotate-0 duration-300">
                                    <div className="w-1/3 h-2 bg-surface-container-highest rounded mb-4" />
                                    <div className="w-full h-1 bg-surface-container rounded mb-2" />
                                    <div className="w-3/4 h-1 bg-surface-container rounded mb-4" />
                                    <div className="flex items-center gap-2 mb-2">
                                        <div className="w-4 h-4 rounded-full bg-primary-fixed-dim" />
                                        <div className="w-1/2 h-1.5 bg-surface-container rounded" />
                                    </div>
                                    <div className="flex items-center gap-2 mb-2">
                                        <div className="w-4 h-4 rounded-full bg-tertiary-fixed-dim" />
                                        <div className="w-2/3 h-1.5 bg-surface-container rounded" />
                                    </div>
                                    <div className="flex items-center gap-2 mb-2">
                                        <div className="w-4 h-4 rounded-full bg-primary-fixed-dim" />
                                        <div className="w-1/2 h-1.5 bg-surface-container rounded" />
                                    </div>
                                    <div className="flex items-center gap-2 mb-2">
                                        <div className="w-4 h-4 rounded-full bg-tertiary-fixed-dim" />
                                        <div className="w-3/5 h-1.5 bg-surface-container rounded" />
                                    </div>
                                    <div className="mt-auto self-end">
                                        <span className="material-symbols-outlined text-outline-variant" style={{fontSize: '40px'}}>edit_document</span>
                                    </div>
                                </div>
                            </div>

                            {/* Right: Structured Extraction Output */}
                            <div className="w-full md:w-1/2 p-md md:p-lg bg-white flex flex-col justify-center gap-sm">
                                <div className="flex items-center gap-3 p-3 rounded-lg border border-outline-variant/50 bg-surface-bright shadow-sm hover:shadow-md transition-shadow">
                                    <div className="w-10 h-10 rounded bg-on-tertiary-container/10 flex items-center justify-center text-on-tertiary-container flex-shrink-0">
                                        <span className="material-symbols-outlined">medication</span>
                                    </div>
                                    <div>
                                        <div className="font-label-md text-label-md text-on-surface">Amoxicillin 500mg</div>
                                        <div className="font-body-sm text-body-sm text-on-surface-variant">Take 1 tablet every 8 hours</div>
                                    </div>
                                    <span className="material-symbols-outlined text-on-tertiary-container ml-auto" style={{fontSize: '18px'}}>check_circle</span>
                                </div>
                                <div className="flex items-center gap-3 p-3 rounded-lg border border-outline-variant/50 bg-surface-bright shadow-sm hover:shadow-md transition-shadow">
                                    <div className="w-10 h-10 rounded bg-secondary/10 flex items-center justify-center text-secondary flex-shrink-0">
                                        <span className="material-symbols-outlined">vital_signs</span>
                                    </div>
                                    <div>
                                        <div className="font-label-md text-label-md text-on-surface">Blood Pressure</div>
                                        <div className="font-body-sm text-body-sm text-on-surface-variant">120/80 mmHg — Normal</div>
                                    </div>
                                    <span className="material-symbols-outlined text-secondary ml-auto" style={{fontSize: '18px'}}>trending_up</span>
                                </div>
                                <div className="flex items-center gap-3 p-3 rounded-lg border border-outline-variant/50 bg-surface-bright shadow-sm hover:shadow-md transition-shadow">
                                    <div className="w-10 h-10 rounded bg-primary-container/10 flex items-center justify-center text-on-primary-container flex-shrink-0">
                                        <span className="material-symbols-outlined">calendar_today</span>
                                    </div>
                                    <div>
                                        <div className="font-label-md text-label-md text-on-surface">Follow-up Appointment</div>
                                        <div className="font-body-sm text-body-sm text-on-surface-variant">Oct 24, 2024 with Dr. Smith</div>
                                    </div>
                                </div>
                            </div>
                        </section>

                        {/* ── How It Works ── */}
                        <section className="w-full max-w-6xl mx-auto flex flex-col items-center">
                            <h2 className="font-headline-md text-headline-md text-on-surface mb-2">Three steps to a smarter health history</h2>
                            <p className="font-body-md text-body-md text-on-surface-variant mb-xl text-center">A seamless pipeline from paper to structured intelligence.</p>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-md w-full">
                                {/* Step 1 */}
                                <div className="bg-surface-container-lowest border border-outline-variant/50 rounded-xl p-md shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group">
                                    <div className="absolute -right-4 -bottom-4 opacity-5 group-hover:opacity-10 transition-opacity">
                                        <span className="material-symbols-outlined" style={{fontSize: '120px'}}>document_scanner</span>
                                    </div>
                                    <div className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider mb-2">Step 1</div>
                                    <h3 className="font-headline-sm text-headline-sm text-on-surface mb-3">Snap &amp; Extract</h3>
                                    <p className="font-body-sm text-body-sm text-on-surface-variant relative z-10">Upload a photo. Our AI reads handwriting and extracts structured data — medicines, dosages, and vitals with clinical precision.</p>
                                </div>
                                {/* Step 2 */}
                                <div className="bg-surface-container-lowest border border-outline-variant/50 rounded-xl p-md shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group">
                                    <div className="absolute -right-4 -bottom-4 opacity-5 group-hover:opacity-10 transition-opacity">
                                        <span className="material-symbols-outlined" style={{fontSize: '120px'}}>forum</span>
                                    </div>
                                    <div className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider mb-2">Step 2</div>
                                    <h3 className="font-headline-sm text-headline-sm text-on-surface mb-3">Ask AI Assistant</h3>
                                    <p className="font-body-sm text-body-sm text-on-surface-variant relative z-10">Chat with your data. Ask things like "What was my last BP reading?" or "Summarize my medications" for instant clarity.</p>
                                </div>
                                {/* Step 3 */}
                                <div className="bg-surface-container-lowest border border-outline-variant/50 rounded-xl p-md shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group">
                                    <div className="absolute -right-4 -bottom-4 opacity-5 group-hover:opacity-10 transition-opacity">
                                        <span className="material-symbols-outlined" style={{fontSize: '120px'}}>share</span>
                                    </div>
                                    <div className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider mb-2">Step 3</div>
                                    <h3 className="font-headline-sm text-headline-sm text-on-surface mb-3">Track &amp; Share</h3>
                                    <p className="font-body-sm text-body-sm text-on-surface-variant relative z-10">View trends over time and share secure links with your doctor to ensure consistent care across providers.</p>
                                </div>
                            </div>
                        </section>

                        {/* ── CTA Banner ── */}
                        <section className="w-full max-w-4xl mx-auto mb-xl">
                            <div className="bg-surface-bright border border-outline-variant/30 rounded-2xl p-xl flex flex-col items-center text-center relative overflow-hidden shadow-sm">

                                <h2 className="font-headline-lg-mobile md:font-headline-lg text-headline-lg-mobile md:text-headline-lg text-on-surface mb-4 relative z-10">
                                    Ready to take control of your health records?
                                </h2>
                                <p className="font-body-md text-body-md text-on-surface-variant mb-lg max-w-xl relative z-10">
                                    Upload your first prescription today and experience the clarity of a structured, searchable medical history.
                                </p>
                                <button
                                    onClick={openUploadModal}
                                    className="bg-on-tertiary-container text-white px-8 py-3 rounded-lg font-label-md text-label-md hover:opacity-90 transition-all shadow-md relative z-10"
                                >
                                    Get Started for Free
                                </button>
                            </div>
                        </section>
                    </>
                ) : (
                    <div className="w-full">
                        <Dashboard key={dashboardRefreshKey} onUploadClick={openUploadModal} />
                    </div>
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

