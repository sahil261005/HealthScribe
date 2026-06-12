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
            <div className="auth-card-container">
                <div className="auth-card">
                    <div className="auth-header">
                        <h1 className="auth-title">HealthScribe</h1>
                        <p className="auth-subtitle">
                            {isLoginMode ? 'Sign in to your account' : 'Create a new account'}
                        </p>
                    </div>

                    {displayError && <div className="error-alert">{displayError}</div>}

                    <form onSubmit={handleSubmit} className="auth-form">
                        <div className="auth-input-group">
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
    );
}

export default AuthPage;
