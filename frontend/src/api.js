import axios from 'axios';

// Set VITE_API_URL in frontend/.env to point at a different backend.
export const SERVER_URL = import.meta.env.VITE_API_URL !== undefined ? import.meta.env.VITE_API_URL.replace(/\/$/, '') : '';
export const API_BASE_URL = `${SERVER_URL}/api`;

export const api = axios.create({ baseURL: API_BASE_URL });

// Turns a server-relative path like /api/images/... into a full URL.
export const serverUrl = (path) => `${SERVER_URL}${path}`;

export const errorMessage = (error, fallback = 'Something went wrong') =>
  error?.response?.data?.detail || error?.message || fallback;

export const getDepartments = () => api.get('/departments');
export const createDepartment = (dept) => api.post('/departments', dept);
export const updateDocumentDepartment = (docId, department) => api.patch(`/documents/${docId}/department`, { department });
export const bulkUpdateDocumentDepartment = (docIds, department) => api.post('/documents/bulk-department', { doc_ids: docIds, department });
export const classifyDocumentDepartment = (docId) => api.post(`/documents/${docId}/classify-department`);
export const reprocessDocument = (docId) => api.post(`/documents/${docId}/reprocess`);
export const bulkReprocessDocuments = (docIds) => api.post('/documents/bulk-reprocess', { doc_ids: docIds });
