// ========================================
// ReplyMan AI Assistant - API Client
// ========================================

class APIClient {
    constructor() {
        this.baseURL = CONFIG.API_BASE_URL;
    }
    
    // Get session token from localStorage
    getToken() {
        return localStorage.getItem(CONFIG.SESSION_KEY);
    }
    
    // Save session token to localStorage
    saveToken(token) {
        if (token) {
            localStorage.setItem(CONFIG.SESSION_KEY, token);
        }
    }
    
    // Clear session token
    clearToken() {
        localStorage.removeItem(CONFIG.SESSION_KEY);
        localStorage.removeItem(CONFIG.USER_KEY);
    }
    
    // Generic request method
    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const token = this.getToken();
        
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include' // Include cookies for session
        };
        
        // Add Authorization header if token exists
        if (token) {
            defaultOptions.headers['Authorization'] = `Bearer ${token}`;
        }
        
        // Merge options
        const finalOptions = {
            ...defaultOptions,
            ...options,
            headers: {
                ...defaultOptions.headers,
                ...options.headers
            }
        };
        
        try {
            const response = await fetch(url, finalOptions);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.message || `HTTP error! status: ${response.status}`);
            }
            
            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }
    
    // Auth endpoints
    async register(email, password, name = null) {
        return this.request('/auth/register', {
            method: 'POST',
            body: JSON.stringify({ email, password, name })
        });
    }
    
    async login(email, password) {
        const result = await this.request('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email, password })
        });
        
        // Save token to localStorage if login successful
        if (result.success && result.session_token) {
            this.saveToken(result.session_token);
        }
        
        return result;
    }
    
    async logout() {
        const result = await this.request('/auth/logout', {
            method: 'POST'
        });
        
        // Clear token from localStorage
        this.clearToken();
        
        return result;
    }
    
    async getCurrentUser() {
        return this.request('/auth/me');
    }
    
    async verifySession() {
        return this.request('/auth/verify');
    }
    
    // Files endpoints
    async uploadFile(file, onProgress = null) {
        const formData = new FormData();
        formData.append('file', file);
        
        const url = `${this.baseURL}/files/upload`;
        const token = this.getToken();
        
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            
            xhr.upload.addEventListener('progress', (e) => {
                if (onProgress && e.lengthComputable) {
                    onProgress(Math.round((e.loaded / e.total) * 100));
                }
            });
            
            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        resolve(JSON.parse(xhr.responseText));
                    } catch (e) {
                        reject(new Error('Invalid JSON response'));
                    }
                } else {
                    reject(new Error(`Upload failed: ${xhr.statusText}`));
                }
            });
            
            xhr.addEventListener('error', () => {
                reject(new Error('Network error during upload'));
            });
            
            xhr.open('POST', url);
            xhr.withCredentials = true;
            
            // Add Authorization header
            if (token) {
                xhr.setRequestHeader('Authorization', `Bearer ${token}`);
            }
            
            xhr.send(formData);
        });
    }
    
    async getFiles() {
        return this.request('/files/list');
    }
    
    async deleteFile(fileId) {
        return this.request(`/files/${fileId}`, {
            method: 'DELETE'
        });
    }
    
    async getFileContent(fileId) {
        return this.request(`/files/${fileId}/content`);
    }
    
    async getContext() {
        return this.request('/files/context');
    }
    
    // Chat endpoints
    async sendMessage(message, sessionId = null, useContext = true) {
        return this.request('/chat/message', {
            method: 'POST',
            body: JSON.stringify({ message, session_id: sessionId, use_context: useContext })
        });
    }
    
    async getChatHistory(sessionId) {
        return this.request(`/chat/history/${sessionId}`);
    }
    
    async clearSession(sessionId) {
        return this.request(`/chat/session/${sessionId}`, {
            method: 'DELETE'
        });
    }
    
    async createNewSession() {
        return this.request('/chat/new-session', {
            method: 'POST'
        });
    }
    
    // Training endpoints
    async startTraining(scenario = 'general') {
        return this.request('/training/start', {
            method: 'POST',
            body: JSON.stringify({ scenario })
        });
    }
    
    async sendTrainingMessage(message, sessionId) {
        return this.request('/training/message', {
            method: 'POST',
            body: JSON.stringify({ message, session_id: sessionId })
        });
    }
    
    async endTraining(sessionId) {
        return this.request('/training/end', {
            method: 'POST',
            body: JSON.stringify({ session_id: sessionId })
        });
    }
    
    async getActiveTraining() {
        return this.request('/training/active');
    }
    
    async getScenarios() {
        return this.request('/training/scenarios');
    }
    
    // Instructions endpoints
    async getInstructions() {
        return this.request('/instructions');
    }
    
    async saveInstructions(instructions) {
        return this.request('/instructions', {
            method: 'POST',
            body: JSON.stringify({ instructions })
        });
    }
    
    async resetInstructions() {
        return this.request('/instructions', {
            method: 'DELETE'
        });
    }
}

// Create singleton instance
const api = new APIClient();
