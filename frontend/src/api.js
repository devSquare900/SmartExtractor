import axios from 'axios';

// Set VITE_API_URL in frontend/.env to point at a different backend.
export const SERVER_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '');
export const API_BASE_URL = `${SERVER_URL}/api`;

export const api = axios.create({ baseURL: API_BASE_URL });

// Turns a server-relative path like /api/images/... into a full URL.
export const serverUrl = (path) => `${SERVER_URL}${path}`;

export const errorMessage = (error, fallback = 'Something went wrong') =>
  error?.response?.data?.detail || error?.message || fallback;
