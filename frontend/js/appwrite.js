// ========================================
// ReplyMan AI Assistant - Appwrite Client
// ========================================

// Note: This is optional - for direct Appwrite integration
// Primary auth flow goes through our backend API

class AppwriteClient {
    constructor() {
        this.client = null;
        this.account = null;
        this.storage = null;
        this.databases = null;
        this.initialized = false;
    }
    
    async init(projectId) {
        if (this.initialized) return;
        
        try {
            // Load Appwrite SDK dynamically
            if (typeof window.Appwrite === 'undefined') {
                await this.loadSDK();
            }
            
            this.client = new window.Appwrite.Client()
                .setEndpoint(CONFIG.APPWRITE_ENDPOINT)
                .setProject(projectId || CONFIG.APPWRITE_PROJECT_ID);
            
            this.account = new window.Appwrite.Account(this.client);
            this.storage = new window.Appwrite.Storage(this.client);
            this.databases = new window.Appwrite.Databases(this.client);
            
            this.initialized = true;
            console.log('Appwrite client initialized');
        } catch (error) {
            console.error('Failed to initialize Appwrite:', error);
        }
    }
    
    async loadSDK() {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/appwrite@14.0.0';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
    
    // Auth methods
    async getSession() {
        if (!this.initialized) return null;
        try {
            return await this.account.get();
        } catch (error) {
            return null;
        }
    }
    
    async logout() {
        if (!this.initialized) return;
        try {
            await this.account.deleteSession('current');
        } catch (error) {
            console.error('Logout error:', error);
        }
    }
}

// Singleton instance
const appwriteClient = new AppwriteClient();
