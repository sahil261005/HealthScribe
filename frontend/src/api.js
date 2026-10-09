import axios from 'axios';

// two separate API clients because we have two backends:
// - Django on port 8000 for auth, records, etc.
// - FastAPI on port 8001 for AI stuff (extraction, chat, embeddings)

const DJANGO_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/';

const djangoBackendApi = axios.create({
    baseURL: DJANGO_URL,
    timeout: 30000, // 30s — Django is lightweight
});

// attach the JWT token to every request if we have one
const attachToken = (config) => {
    const accessToken = localStorage.getItem('access_token');

    if (accessToken) {
        config.headers.Authorization = `Bearer ${accessToken}`;
    }

    return config;
};

djangoBackendApi.interceptors.request.use(attachToken, (error) => Promise.reject(error));

// access tokens only last 1 day, so when one expires we get a new one
// with the refresh token instead of logging the user out.
// if a few requests fail at the same time we only refresh once
let refreshPromise = null;

const refreshAccessToken = () => {
    if (!refreshPromise) {
        const refreshToken = localStorage.getItem('refresh_token');

        refreshPromise = axios.post(`${DJANGO_URL}auth/refresh/`, { refresh: refreshToken })
            .then((response) => {
                localStorage.setItem('access_token', response.data.access);
                // django gives us a new refresh token every time (rotation), save it too
                if (response.data.refresh) {
                    localStorage.setItem('refresh_token', response.data.refresh);
                }
                return response.data.access;
            })
            .finally(() => {
                refreshPromise = null;
            });
    }
    return refreshPromise;
};

// when a request fails with 401, refresh the token and try the request one more time
const retryWithNewToken = async (error, client) => {
    const originalRequest = error.config;
    const url = originalRequest?.url || '';

    const shouldRetry = originalRequest
        && !originalRequest._retried
        && localStorage.getItem('refresh_token')
        && !url.includes('auth/login')
        && !url.includes('auth/refresh');

    if (!shouldRetry) {
        return Promise.reject(error);
    }

    originalRequest._retried = true;

    try {
        const newAccessToken = await refreshAccessToken();
        originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
        return client(originalRequest);
    } catch {
        // refresh token expired too, so the user has to log in again
        console.log('Session expired - logging out');
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.location.reload();
        return Promise.reject(error);
    }
};

djangoBackendApi.interceptors.response.use(
    (response) => {
        return response;
    },
    (error) => {
        if (error.response?.status === 401) {
            return retryWithNewToken(error, djangoBackendApi);
        }

        return Promise.reject(error);
    }
);

// AI service — generous timeout because Render free tier cold-starts
// can take 30-60s, plus Gemini processing adds more time
export const aiService = axios.create({
    baseURL: import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001/',
    timeout: 120000, // 120s — cold start + AI model processing
});

// the AI service checks the same login token as django
aiService.interceptors.request.use(attachToken, (error) => Promise.reject(error));

// Intercept AI service errors to produce actionable messages
aiService.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            return retryWithNewToken(error, aiService);
        }

        if (error.code === 'ECONNABORTED') {
            // axios timeout — request took too long
            error.friendlyMessage = 'The AI service is taking too long to respond. It may be waking up — please try again in a minute.';
        } else if (!error.response) {
            // network error — service is completely unreachable
            error.friendlyMessage = 'Cannot reach the AI service. It may be starting up (free tier). Please wait ~60 seconds and try again.';
        } else if (error.response?.data?.detail) {
            const detail = error.response.data.detail;
            const detailStr = typeof detail === 'string' ? detail : JSON.stringify(detail);
            if (detailStr.includes('429') || detailStr.includes('RESOURCE_EXHAUSTED') || detailStr.includes('Quota exceeded') || detailStr.includes('quota')) {
                error.friendlyMessage = 'Daily AI quota exceeded for Gemini free tier. Please switch to Regional / Indian Scripts (Sarvam) or wait for quota reset.';
            } else if (error.response.status === 503) {
                error.friendlyMessage = detailStr || 'AI service is temporarily unavailable. Please try again shortly.';
            } else {
                error.friendlyMessage = detailStr;
            }
        }
        return Promise.reject(error);
    }
);

export default djangoBackendApi;
