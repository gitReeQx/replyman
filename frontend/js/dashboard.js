// ========================================
// ReplyMan AI Assistant - Dashboard Logic
// Исправлено: правильное получение контекста
// ========================================

let currentSessionId = null;
let messageCount = 0;

document.addEventListener('DOMContentLoaded', () => {
    initDashboard();
});

async function initDashboard() {
    await checkAuth();
    initSidebar();
    initChat();
    loadStats();
}

async function checkAuth() {
    try {
        const result = await api.getCurrentUser();
        if (result.success && result.user) {
            document.getElementById('userName').textContent = result.user.name || 'Пользователь';
            document.getElementById('userEmail').textContent = result.user.email;
            document.getElementById('userAvatar').textContent = (result.user.name || result.user.email)[0].toUpperCase();
        } else {
            window.location.href = 'index.html';
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        window.location.href = 'index.html';
    }
}

function initSidebar() {
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const sidebar = document.getElementById('sidebar');
    
    mobileMenuBtn.addEventListener('click', () => {
        sidebar.classList.toggle('open');
    });
    
    document.addEventListener('click', (e) => {
        if (window.innerWidth <= 1024 && 
            !sidebar.contains(e.target) && 
            !mobileMenuBtn.contains(e.target) &&
            sidebar.classList.contains('open')) {
            sidebar.classList.remove('open');
        }
    });
    
    document.getElementById('logoutBtn').addEventListener('click', async () => {
        try {
            await api.logout();
        } catch (error) {
            console.error('Logout error:', error);
        }
        localStorage.removeItem(CONFIG.USER_KEY);
        window.location.href = 'index.html';
    });
}

function initChat() {
    const chatInput = document.getElementById('chatInput');
    const sendBtn = document.getElementById('sendBtn');
    
    // Auto-resize textarea
    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + 'px';
    });
    
    // Send on Enter (without Shift)
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    // Send button click
    sendBtn.addEventListener('click', sendMessage);
    
    // Create new session
    createNewSession();
}

async function createNewSession() {
    try {
        const result = await api.createNewSession();
        if (result.success) {
            currentSessionId = result.session_id;
        }
    } catch (error) {
        console.error('Failed to create session:', error);
    }
}

async function sendMessage() {
    const chatInput = document.getElementById('chatInput');
    const sendBtn = document.getElementById('sendBtn');
    const message = chatInput.value.trim();
    
    if (!message) return;
    
    // Disable input
    chatInput.disabled = true;
    sendBtn.disabled = true;
    
    // Add user message to UI
    addMessage(message, 'user');
    chatInput.value = '';
    chatInput.style.height = 'auto';
    
    // Show typing indicator
    showTypingIndicator();
    
    try {
        // ========== ИСПРАВЛЕНО: Передаём контекст из users.knowledge ==========
        const result = await api.sendMessage(message, currentSessionId, true);
        
        // Remove typing indicator
        hideTypingIndicator();
        
        if (result.success) {
            addMessage(result.response, 'assistant');
            currentSessionId = result.session_id;
            messageCount++;
            updateStats();
        } else {
            addMessage('Ошибка при получении ответа. Попробуйте ещё раз.', 'assistant');
        }
    } catch (error) {
        console.error('Send message error:', error);
        hideTypingIndicator();
        addMessage('Ошибка соединения. Проверьте подключение.', 'assistant');
    } finally {
        chatInput.disabled = false;
        sendBtn.disabled = false;
        chatInput.focus();
    }
}

function addMessage(content, role) {
    const messagesContainer = document.getElementById('chatMessages');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    const avatar = role === 'user' ? '👤' : '🤖';
    
    messageDiv.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">
            <div class="message-text">${formatMessage(content)}</div>
        </div>
    `;
    
    messagesContainer.appendChild(messageDiv);
    
    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function formatMessage(content) {
    return content
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>');
}

function showTypingIndicator() {
    const messagesContainer = document.getElementById('chatMessages');
    
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message assistant';
    typingDiv.id = 'typingIndicator';
    
    typingDiv.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="typing-indicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;
    
    messagesContainer.appendChild(typingDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function hideTypingIndicator() {
    const typingIndicator = document.getElementById('typingIndicator');
    if (typingIndicator) {
        typingIndicator.remove();
    }
}

async function loadStats() {
    try {
        // Load knowledge stats
        const statsResult = await api.request('/files/stats');
        if (statsResult.success) {
            document.getElementById('filesCount').textContent = 
                statsResult.knowledge_size > 0 ? '✓' : '0';
        }
        
        // Load message count
        const savedCount = localStorage.getItem('messageCount') || 0;
        messageCount = parseInt(savedCount);
        document.getElementById('messagesCount').textContent = messageCount;
        
        // Trainings count
        const trainingsCount = localStorage.getItem('trainingsCount') || 0;
        document.getElementById('trainingsCount').textContent = trainingsCount;
        
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

function updateStats() {
    document.getElementById('messagesCount').textContent = messageCount;
    localStorage.setItem('messageCount', messageCount);
}
