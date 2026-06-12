import React, { createContext, useContext, useState, useEffect } from 'react';
import djangoBackendApi from '../api';

// context for managing login state across the app
// stores JWT tokens in localStorage so users stay logged in on refresh

const AuthContext = createContext(null);

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);

    // on mount, check if we have a saved token and if it's still valid
    useEffect(() => {
        const checkExistingAuth = async () => {
            const savedToken = localStorage.getItem('access_token');

            if (savedToken) {
                try {
                    const response = await djangoBackendApi.get('auth/profile/', {
                        headers: {
                            Authorization: `Bearer ${savedToken}`
                        }
                    });

                    setUser(response.data);
                } catch {
                    // token is bad, clear it
                    console.log('Saved token is invalid, clearing...');
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('refresh_token');
                }
            }

            setIsLoading(false);
        };

        checkExistingAuth();
    }, []);

    const register = async (username, email, password) => {
        setError(null);

        try {
            const response = await djangoBackendApi.post('auth/register/', {
                username,
                email,
                password
            });

            const { tokens, user: userData } = response.data;
            localStorage.setItem('access_token', tokens.access);
            localStorage.setItem('refresh_token', tokens.refresh);

            setUser({
                username: userData.username,
                email: userData.email
            });

            return { success: true };

        } catch (error) {
            const errorMessage = error.response?.data?.username?.[0]
                || error.response?.data?.email?.[0]
                || error.response?.data?.password?.[0]
                || 'Registration failed. Please try again.';
            setError(errorMessage);
            return { success: false, error: errorMessage };
        }
    };

    const login = async (username, password) => {
        setError(null);

        try {
            const tokenResponse = await djangoBackendApi.post('auth/login/', {
                username,
                password
            });

            const { access, refresh } = tokenResponse.data;

            localStorage.setItem('access_token', access);
            localStorage.setItem('refresh_token', refresh);

            // grab the user's profile now that we're authenticated
            const profileResponse = await djangoBackendApi.get('auth/profile/', {
                headers: {
                    Authorization: `Bearer ${access}`
                }
            });

            setUser(profileResponse.data);

            return { success: true };

        } catch (error) {
            const errorMessage = error.response?.data?.detail
                || 'Invalid username or password.';
            setError(errorMessage);
            return { success: false, error: errorMessage };
        }
    };

    const logout = () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        setUser(null);
        setError(null);
    };

    const getAccessToken = () => {
        return localStorage.getItem('access_token');
    };

    const authContextValue = {
        user,
        isLoading,
        error,
        isAuthenticated: !!user,
        register,
        login,
        logout,
        getAccessToken
    };

    return (
        <AuthContext.Provider value={authContextValue}>
            {children}
        </AuthContext.Provider>
    );
};

export default AuthContext;
