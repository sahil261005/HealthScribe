import axios from 'axios';

// we have two backend services so we need two axios instances
// 1. django (port 8000) - handles users and data storage
// 2. fastapi (port 8001) - handles AI stuff like extraction and chatbot

// django backend api
const djangoBackendApi = axios.create({
    baseURL: 'http://localhost:8000/api/',
});

// this interceptor automatically adds the JWT token to every request
// so we dont have to manually add it in every component
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

// handle expired tokens
// right now we just let the error go through and AuthContext handles logging out
// TODO: could add automatic token refresh here later
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

// fastapi ai service - doesnt need auth since its an internal service
export const aiService = axios.create({
    baseURL: 'http://localhost:8001/',
});

export default djangoBackendApi;
