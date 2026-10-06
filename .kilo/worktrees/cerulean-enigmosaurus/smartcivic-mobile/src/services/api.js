import axios from 'axios';
import * as SecureStore from 'expo-secure-store';

// Set default API base URL using laptop IPv4 network address
export const DEFAULT_API_URL = 'http://10.30.128.225:5000/api';

const api = axios.create({
  baseURL: DEFAULT_API_URL,
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
  }
});

// Request interceptor attaching stored JWT Bearer token
api.interceptors.request.use(
  async (config) => {
    try {
      const token = await SecureStore.getItemAsync('user_token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    } catch (err) {
      console.warn('SecureStore token read error:', err);
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor handling unauthorized tokens
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response && error.response.status === 401) {
      try {
        await SecureStore.deleteItemAsync('user_token');
      } catch (e) {}
    }
    return Promise.reject(error);
  }
);

export default api;
