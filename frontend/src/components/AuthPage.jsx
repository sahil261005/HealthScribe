import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { User, Mail, Lock, ArrowRight, Loader2, Heart } from 'lucide-react';

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
                // basic email check before sending to server
                if (!email.includes('@')) {
                    setFormError('Please enter a valid email address.');
                    setIsSubmitting(false);
                    return;
                }
                result = await register(username, email, password);
            }
            if (!result.success) setFormError(result.error);
        } catch (err) {
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
            <div className="auth-card-container">
                <div className="auth-card">
                    <div className="auth-header">
                        <div className="auth-logo-box">
                            <Heart size={28} />
                        </div>
                        <h1 className="auth-title">HealthScribe</h1>
                        <p className="auth-subtitle">
                            {isLoginMode ? 'Welcome back! Sign in to continue.' : 'Create an account to get started.'}
                        </p>
                    </div>

                    {displayError && <div className="error-alert">{displayError}</div>}

                    <form onSubmit={handleSubmit} className="auth-form">
                        <div className="auth-input-group">
                            <User className="auth-input-icon" size={18} />
                            <input
                                type="text"
                                placeholder="Username"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                required
                                className="auth-input"
                            />
                        </div>

                        {!isLoginMode && (
                            <div className="auth-input-group">
                                <Mail className="auth-input-icon" size={18} />
                                <input
                                    type="email"
                                    placeholder="Email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    required
                                    className="auth-input"
                                />
                            </div>
                        )}

                        <div className="auth-input-group">
                            <Lock className="auth-input-icon" size={18} />
                            <input
                                type="password"
                                placeholder="Password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                className="auth-input"
                            />
                        </div>

                        <button type="submit" disabled={isSubmitting} className="btn-auth-submit">
                            {isSubmitting ? (
                                <Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} />
                            ) : (
                                <>
                                    {isLoginMode ? 'Sign In' : 'Create Account'}
                                    <ArrowRight size={18} />
                                </>
                            )}
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
    );
}

export default AuthPage;
