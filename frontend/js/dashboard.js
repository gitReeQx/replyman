// ========================================
// ReplyMan AI Assistant - Dashboard Logic
// Поддержка Markdown (блоки кода, жирный текст и т.д.)
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
    await addMessage(message, 'user');
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
            await addMessage(result.response, 'assistant');
            currentSessionId = result.session_id;
            messageCount++;
            updateStats();
        } else {
            await addMessage('Ошибка при получении ответа. Попробуйте ещё раз.', 'assistant');
        }
    } catch (error) {
        console.error('Send message error:', error);
        hideTypingIndicator();
        await addMessage('Ошибка соединения. Проверьте подключение.', 'assistant');
    } finally {
        chatInput.disabled = false;
        sendBtn.disabled = false;
        chatInput.focus();
    }
}

// ========== НОВЫЕ ФУНКЦИИ ДЛЯ ПОДДЕРЖКИ MARKDOWN ==========

/**
 * Экранирует HTML-спецсимволы (для безопасности)
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Форматирует сообщение:
 * - для ассистента: рендерит Markdown через marked.js
 * - для пользователя: экранирует HTML и заменяет переносы строк
 */
async function formatMessage(content, isAssistant = false) {
    if (isAssistant) {
        try {
            // Проверяем, что marked загружен
            if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
                const html = await marked.parse(content);
                return html;
            } else {
                console.warn('marked.js не загружен, используется базовое форматирование');
                return escapeHtml(content).replace(/\n/g, '<br>');
            }
        } catch (e) {
            console.error('Markdown parse error:', e);
            return escapeHtml(content).replace(/\n/g, '<br>');
        }
    } else {
        // Сообщения пользователя показываем как обычный текст (безопасно)
        return escapeHtml(content).replace(/\n/g, '<br>');
    }
}

/**
 * Добавляет сообщение в чат с поддержкой Markdown для ассистента
 */
async function addMessage(content, role) {
    const messagesContainer = document.getElementById('chatMessages');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    const avatar = role === 'user' ? '👤' : '<img src="robot_avatar.png" alt="AI">';
    const formattedContent = await formatMessage(content, role === 'assistant');
    
    messageDiv.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">
            <div class="message-text">${formattedContent}</div>
        </div>
    `;
    
    messagesContainer.appendChild(messageDiv);
    
    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    if (role === 'assistant') {
        addCopyButtonsToCodeBlocks();
    }
}

function addCopyButtonsToCodeBlocks() {
    const messageTexts = document.querySelectorAll('.message.assistant .message-text');
    messageTexts.forEach(container => {
        const pres = container.querySelectorAll('pre');
        pres.forEach(pre => {
            // Если кнопка уже есть – пропускаем
            if (pre.querySelector('.copy-btn')) return;
            
            const btn = document.createElement('button');
            btn.className = 'copy-btn';
            btn.textContent = 'Копировать';
            pre.style.position = 'relative';
            pre.appendChild(btn);
            
            btn.addEventListener('click', async () => {
                const code = pre.querySelector('code');
                const text = code ? code.innerText : pre.innerText;
                try {
                    await navigator.clipboard.writeText(text);
                    btn.textContent = 'Скопировано!';
                    btn.classList.add('copied');
                    setTimeout(() => {
                        btn.textContent = 'Копировать';
                        btn.classList.remove('copied');
                    }, 2000);
                } catch (err) {
                    console.error('Ошибка копирования:', err);
                    btn.textContent = 'Ошибка';
                    setTimeout(() => {
                        btn.textContent = 'Копировать';
                    }, 1500);
                }
            });
        });
    });
}

// ========== ОСТАЛЬНЫЕ ФУНКЦИИ БЕЗ ИЗМЕНЕНИЙ ==========

function showTypingIndicator() {
    const messagesContainer = document.getElementById('chatMessages');
    
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message assistant';
    typingDiv.id = 'typingIndicator';
    
    typingDiv.innerHTML = `
        <div class="message-avatar"><img src="robot_avatar.png" alt="AI"></div>
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
        // Получаем все счётчики с сервера (Appwrite)
        const statsResult = await api.request('/auth/stats');
        if (statsResult.success) {
            document.getElementById('filesCount').textContent = statsResult.files_count || 0;
            document.getElementById('messagesCount').textContent = statsResult.messages_count || 0;
            document.getElementById('trainingsCount').textContent = statsResult.trainings_count || 0;
            messageCount = statsResult.messages_count || 0;
        } else {
            // Fallback: загрузка через /files/stats
            const filesResult = await api.request('/files/stats');
            if (filesResult.success) {
                document.getElementById('filesCount').textContent = filesResult.files_count || 0;
            }
        }
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

function updateStats() {
    // Обновляем счётчик сообщений локально + на сервере
    messageCount++;
    document.getElementById('messagesCount').textContent = messageCount;
    // Счётчик инкрементируется на бэкенде при отправке сообщения
}