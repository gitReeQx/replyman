// ========================================
// ReplyMan AI Assistant - Configuration
// ========================================

const CONFIG = {
    // Backend API URL
    API_BASE_URL: 'https://api.ourbit.ru/replyman/api',
    
    // Appwrite Configuration
    APPWRITE_ENDPOINT: 'https://api.ourbit.ru/v1',
    APPWRITE_PROJECT_ID: '',
    
    // App URL
    APP_URL: 'https://replyman.ru',
    
    // Session storage keys
    SESSION_KEY: 'replyman_session',
    USER_KEY: 'replyman_user',
    
    // File upload settings
    MAX_FILE_SIZE: 30 * 1024 * 1024, // 10MB
    ALLOWED_EXTENSIONS: ['.txt', '.json', '.html', '.htm'],
    
    // Chat settings
    MAX_MESSAGE_LENGTH: 4000,
    
    // UI settings
    TYPING_DELAY: 1500
};

Object.freeze(CONFIG);
