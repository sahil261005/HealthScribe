import axios from 'axios';

// two separate API clients because we have two backends:
// - Django on port 8000 for auth, records, etc.
// - FastAPI on port 8001 for AI stuff (extraction, chat, embeddings)

const djangoBackendApi = axios.create({
    baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api/',
    timeout: 30000, // 30s — Django is lightweight
});

// attach the JWT token to every request if we have one
djangoBackendApi.interceptors.request.use(
    (config) => {
        const accessToken = localStorage.getItem('access_token');

        if (accessToken) {
            config.headers.Authorization = `Bearer ${accessToken}`;
        }

        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

// log when auth fails (usually means the token expired)
djangoBackendApi.interceptors.response.use(
    (response) => {
        return response;
    },
    (error) => {
        if (error.response?.status === 401) {
            console.log('Authentication failed - token may be expired');
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

// Intercept AI service errors to produce actionable messages
aiService.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.code === 'ECONNABORTED') {
            // axios timeout — request took too long
            error.friendlyMessage = 'The AI service is taking too long to respond. It may be waking up — please try again in a minute.';
        } else if (!error.response) {
            // network error — service is completely unreachable
            error.friendlyMessage = 'Cannot reach the AI service. It may be starting up (free tier). Please wait ~60 seconds and try again.';
        } else if (error.response.status === 503) {
            error.friendlyMessage = error.response.data?.detail || 'AI service is temporarily unavailable. Please try again shortly.';
        }
        return Promise.reject(error);
    }
);

export default djangoBackendApi;
