import React, { createContext, useContext, useState, useEffect } from 'react';
import djangoBackendApi from '../api';

// auth context - provides login/register/logout to the whole app
// stores jwt tokens in localStorage so users stay logged in after closing browser

const AuthContext = createContext(null);

// custom hook so components can easily access auth stuff
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

    // check if theres already a saved token when the app loads
    // if the token is still valid we auto-login the user
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

                    // token works, set the user
                    setUser(response.data);
                } catch (error) {
                    // token is expired or invalid, clear everything
                    console.log('Saved token is invalid, clearing...');
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('refresh_token');
                }
            }

            setIsLoading(false);
        };

        checkExistingAuth();
    }, []);

    // register a new user and auto-login them
    const register = async (username, email, password) => {
        setError(null);

        try {
            const response = await djangoBackendApi.post('auth/register/', {
                username,
                email,
                password
            });

            // save tokens so they stay logged in
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

    // login an existing user
    const login = async (username, password) => {
        setError(null);

        try {
            // first get the jwt tokens
            const tokenResponse = await djangoBackendApi.post('auth/login/', {
                username,
                password
            });

            const { access, refresh } = tokenResponse.data;

            localStorage.setItem('access_token', access);
            localStorage.setItem('refresh_token', refresh);

            // then fetch their profile
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

    // logout - just clear everything
    const logout = () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        setUser(null);
        setError(null);
    };

    const getAccessToken = () => {
        return localStorage.getItem('access_token');
    };

    // all the stuff we want to share with the rest of the app
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
