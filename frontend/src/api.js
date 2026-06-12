import axios from 'axios';

// two separate API clients because we have two backends:
// - Django on port 8000 for auth, records, etc.
// - FastAPI on port 8001 for AI stuff (extraction, chat, embeddings)

const djangoBackendApi = axios.create({
    baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api/',
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

// AI service doesn't need auth headers for now (it's internal)
export const aiService = axios.create({
    baseURL: import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8001/',
});

export default djangoBackendApi;
