import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';

function AuthPage() {
    const [isLoginMode, setIsLoginMode] = useState(true);
    const [username, setUsername] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [formError, setFormError] = useState('');
    const { login, register, error: authError } = useAuth();

    const handleSubmit = async (e) => {
        e.preventDefault();
        setFormError('');
        setIsSubmitting(true);
        try {
            let result;
            if (isLoginMode) {
                result = await login(username, password);
            } else {
                if (!email.includes('@')) {
                    setFormError('Please enter a valid email address.');
                    setIsSubmitting(false);
                    return;
                }
                result = await register(username, email, password);
            }
            if (!result.success) setFormError(result.error);
        } catch {
            setFormError('Something went wrong. Please try again.');
        } finally {
            setIsSubmitting(false);
        }
    };

    const toggleMode = () => {
        setIsLoginMode(!isLoginMode);
        setFormError('');
        setUsername('');
        setEmail('');
        setPassword('');
    };

    const displayError = formError || authError;

    return (
        <div className="auth-page">
            <div className="auth-split-layout">
                <div className="auth-info-side">
                    <h1 className="auth-tagline">
                        Your Prescriptions, Digitized and Searchable
                    </h1>
                    <p className="auth-description">
                        Upload a photo of any handwritten or printed prescription and get clean, structured medical records you can search, review, and share with your doctor.
                    </p>

                    <div className="auth-feature-list">
                        <div className="auth-feature-item">
                            <span className="auth-feature-icon">1</span>
                            <div className="auth-feature-text">
                                <div className="auth-feature-title">Snap and Extract</div>
                                Take a photo of your prescription. The app reads the handwriting and pulls out medicines, dosages, vitals, and allergies automatically.
                            </div>
                        </div>
                        <div className="auth-feature-item">
                            <span className="auth-feature-icon">2</span>
                            <div className="auth-feature-text">
                                <div className="auth-feature-title">Ask About Your Health</div>
                                Chat with your medical history in plain language. Ask things like "what was I prescribed for my headache last month?" and get instant answers.
                            </div>
                        </div>
                        <div className="auth-feature-item">
                            <span className="auth-feature-icon">3</span>
                            <div className="auth-feature-text">
                                <div className="auth-feature-title">Share Securely</div>
                                Generate a private link to share any record with your doctor or family — no account needed on their end.
                            </div>
                        </div>
                    </div>
                </div>

                <div className="auth-card-side">
                    <div className="auth-card">
                        <div className="auth-header">
                            <h2 className="auth-title">
                                {isLoginMode ? 'Welcome Back' : 'Create Account'}
                            </h2>
                        </div>

                        {displayError && <div className="error-alert">{displayError}</div>}

                        <form onSubmit={handleSubmit} className="auth-form">
                            <div className="auth-input-group">
                                <label className="auth-label">Username</label>
                                <input
                                    type="text"
                                    placeholder="Enter your username"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    required
                                    className="auth-input"
                                />
                            </div>

                            {!isLoginMode && (
                                <div className="auth-input-group">
                                    <label className="auth-label">Email</label>
                                    <input
                                        type="email"
                                        placeholder="Enter your email"
                                        value={email}
                                        onChange={(e) => setEmail(e.target.value)}
                                        required
                                        className="auth-input"
                                    />
                                </div>
                            )}

                            <div className="auth-input-group">
                                <label className="auth-label">Password</label>
                                <input
                                    type="password"
                                    placeholder="Enter your password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                    className="auth-input"
                                />
                            </div>

                            <button type="submit" disabled={isSubmitting} className="btn-auth-submit">
                                {isSubmitting ? 'Please wait...' : (isLoginMode ? 'Sign In' : 'Create Account')}
                            </button>
                        </form>

                        <div className="auth-footer">
                            <p>
                                {isLoginMode ? "Don't have an account?" : "Already have an account?"}
                                <button type="button" onClick={toggleMode} className="btn-link">
                                    {isLoginMode ? 'Sign up' : 'Sign in'}
                                </button>
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default AuthPage;
