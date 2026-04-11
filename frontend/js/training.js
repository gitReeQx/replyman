// ========================================
// ReplyMan AI Assistant - Training Page Logic
// ========================================

let currentTrainingSessionId = null;
let messageCounter = 0;
let currentScenario = 'general';

document.addEventListener('DOMContentLoaded', () => {
    initTrainingPage();
});

async function initTrainingPage() {
    // Check authentication
    await checkAuth();
    
    // Initialize components
    initSidebar();
    initTraining();
    
    // Check for active training session (persisted in Appwrite)
    await restoreActiveTraining();
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
        } catch (error) {}
        localStorage.removeItem(CONFIG.USER_KEY);
        window.location.href = 'index.html';
    });
}

function initTraining() {
    // Scenario selection
    const scenarioCards = document.querySelectorAll('.scenario-card');
    scenarioCards.forEach(card => {
        card.addEventListener('click', () => {
            scenarioCards.forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            currentScenario = card.dataset.scenario;
        });
    });
    
    // Start training button
    document.getElementById('startTrainingBtn').addEventListener('click', startTraining);
    
    // Training input
    const trainingInput = document.getElementById('trainingInput');
    const trainingSendBtn = document.getElementById('trainingSendBtn');
    
    trainingInput.addEventListener('input', () => {
        trainingInput.style.height = 'auto';
        trainingInput.style.height = Math.min(trainingInput.scrollHeight, 150) + 'px';
    });
    
    trainingInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendTrainingMessage();
        }
    });
    
    trainingSendBtn.addEventListener('click', sendTrainingMessage);
    
    // End training button
    document.getElementById('endTrainingBtn').addEventListener('click', endTraining);
    
    // New training button
    document.getElementById('newTrainingBtn').addEventListener('click', resetTraining);
}

async function startTraining() {
    const startBtn = document.getElementById('startTrainingBtn');
    startBtn.disabled = true;
    startBtn.innerHTML = '<span class="spinner" style="width: 20px; height: 20px;"></span>';
    
    showAlert('Запуск тренировки...', 'info');
    
    try {
        const result = await api.startTraining(currentScenario);
        
        if (result.success) {
            currentTrainingSessionId = result.session_id;
            messageCounter = 0;
            
            // Show training chat
            document.getElementById('scenarioSelection').classList.add('hidden');
            document.getElementById('trainingChat').classList.remove('hidden');
            document.getElementById('trainingFeedback').classList.add('hidden');
            
            // Update status
            updateTrainingStatus(true);
            
            // Add initial message from "client"
            addTrainingMessage(result.response, 'client');
            
            showAlert('', '');
        } else {
            showAlert('Ошибка запуска тренировки', 'error');
        }
    } catch (error) {
        showAlert('Ошибка соединения', 'error');
    } finally {
        startBtn.disabled = false;
        startBtn.innerHTML = '🚀 Начать тренировку';
    }
}

async function sendTrainingMessage() {
    const trainingInput = document.getElementById('trainingInput');
    const trainingSendBtn = document.getElementById('trainingSendBtn');
    const message = trainingInput.value.trim();
    
    if (!message) return;
    
    // Disable input
    trainingInput.disabled = true;
    trainingSendBtn.disabled = true;
    
    // Add employee message
    addTrainingMessage(message, 'employee');
    trainingInput.value = '';
    trainingInput.style.height = 'auto';
    
    // Show typing indicator
    showTypingIndicator();
    
    try {
        const result = await api.sendTrainingMessage(message, currentTrainingSessionId);
        
        hideTypingIndicator();
        
        if (result.success) {
            addTrainingMessage(result.response, 'client');
            messageCounter++;
            updateMessageCounter();
        } else {
            addTrainingMessage('Ошибка. Попробуйте еще раз.', 'client');
        }
    } catch (error) {
        hideTypingIndicator();
        addTrainingMessage('Ошибка соединения', 'client');
    } finally {
        trainingInput.disabled = false;
        trainingSendBtn.disabled = false;
        trainingInput.focus();
    }
}

async function endTraining() {
    const endBtn = document.getElementById('endTrainingBtn');
    endBtn.disabled = true;
    endBtn.innerHTML = 'Завершение...';
    
    showAlert('Анализ диалога...', 'info');
    
    try {
        const result = await api.endTraining(currentTrainingSessionId);
        
        if (result.success) {
            // Show feedback
            showFeedback(result);
            // Счётчик тренировок инкрементируется на бэкенде при завершении
        } else {
            showAlert('Ошибка завершения тренировки', 'error');
        }
    } catch (error) {
        showAlert('Ошибка соединения', 'error');
    } finally {
        endBtn.disabled = false;
        endBtn.innerHTML = '🏁 Завершить тренировку';
    }
}

async function restoreActiveTraining() {
    try {
        const result = await api.getActiveTraining();
        
        if (result.success && result.active && result.session_id) {
            currentTrainingSessionId = result.session_id;
            currentScenario = result.scenario || 'general';
            const conversation = result.conversation || [];
            
            // Select correct scenario card
            const scenarioCards = document.querySelectorAll('.scenario-card');
            scenarioCards.forEach(c => {
                c.classList.toggle('selected', c.dataset.scenario === currentScenario);
            });
            
            // Show training chat
            document.getElementById('scenarioSelection').classList.add('hidden');
            document.getElementById('trainingChat').classList.remove('hidden');
            document.getElementById('trainingFeedback').classList.add('hidden');
            updateTrainingStatus(true);
            
            // Restore conversation
            conversation.forEach(msg => {
                if (msg.role === 'user') {
                    addTrainingMessage(msg.content, 'client');
                } else if (msg.role === 'assistant') {
                    addTrainingMessage(msg.content, 'employee');
                    messageCounter++;
                }
            });
            updateMessageCounter();
            
            showAlert('Тренировка восстановлена', 'info');
            setTimeout(() => showAlert('', ''), 2000);
        }
    } catch (error) {
        console.warn('Failed to restore active training:', error);
    }
}

function resetTraining() {
    currentTrainingSessionId = null;
    messageCounter = 0;
    
    // Clear messages
    document.getElementById('trainingMessages').innerHTML = '';
    
    // Show scenario selection
    document.getElementById('scenarioSelection').classList.remove('hidden');
    document.getElementById('trainingChat').classList.add('hidden');
    document.getElementById('trainingFeedback').classList.add('hidden');
    
    // Update status
    updateTrainingStatus(false);
    
    showAlert('', '');
}

function addTrainingMessage(content, role) {
    const messagesContainer = document.getElementById('trainingMessages');
    
    const messageDiv = document.createElement('div');
    const messageClass = role === 'employee' ? 'user' : 'assistant';
    messageDiv.className = `message ${messageClass}`;
    
    const avatar = role === 'employee' ? '👤' : '👤'; // Both show person icon
    const label = role === 'employee' ? 'Сотрудник' : 'Клиент';
    
    messageDiv.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">
            <div style="font-size: 0.8rem; color: var(--primary-color); margin-bottom: 5px;">${label}</div>
            <div class="message-text">${formatMessage(content)}</div>
        </div>
    `;
    
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function showTypingIndicator() {
    const messagesContainer = document.getElementById('trainingMessages');
    
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message assistant';
    typingDiv.id = 'trainingTypingIndicator';
    
    typingDiv.innerHTML = `
        <div class="message-avatar">👤</div>
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
    const typingIndicator = document.getElementById('trainingTypingIndicator');
    if (typingIndicator) {
        typingIndicator.remove();
    }
}

function showFeedback(feedback) {
    // Hide chat, show feedback
    document.getElementById('trainingChat').classList.add('hidden');
    document.getElementById('trainingFeedback').classList.remove('hidden');
    
    // Update status
    updateTrainingStatus(false);
    
    // Fill in feedback data
    const score = feedback.overall_score || 0;
    document.getElementById('feedbackScore').textContent = score.toFixed(1);
    
    // Strengths
    const strengthsList = document.getElementById('strengthsList');
    strengthsList.innerHTML = '';
    if (feedback.strengths && feedback.strengths.length > 0) {
        feedback.strengths.forEach(item => {
            strengthsList.innerHTML += `<li>${item}</li>`;
        });
    } else {
        strengthsList.innerHTML = '<li>Не определено</li>';
    }
    
    // Weaknesses
    const weaknessesList = document.getElementById('weaknessesList');
    weaknessesList.innerHTML = '';
    if (feedback.weaknesses && feedback.weaknesses.length > 0) {
        feedback.weaknesses.forEach(item => {
            weaknessesList.innerHTML += `<li>${item}</li>`;
        });
    } else {
        weaknessesList.innerHTML = '<li>Не определено</li>';
    }
    
    // Recommendations
    const recommendationsList = document.getElementById('recommendationsList');
    recommendationsList.innerHTML = '';
    if (feedback.recommendations && feedback.recommendations.length > 0) {
        feedback.recommendations.forEach(item => {
            recommendationsList.innerHTML += `<li>${item}</li>`;
        });
    } else {
        recommendationsList.innerHTML = '<li>Не определено</li>';
    }
    
    // Full feedback
    document.getElementById('fullFeedback').textContent = feedback.full_feedback || 'Обратная связь недоступна';
    
    showAlert('', '');
}

function updateTrainingStatus(isActive) {
    const status = document.getElementById('trainingStatus');
    const statusText = document.getElementById('trainingStatusText');
    
    if (isActive) {
        status.classList.remove('inactive');
        statusText.textContent = 'Тренировка активна';
    } else {
        status.classList.add('inactive');
        statusText.textContent = 'Тренировка не начата';
    }
}

function updateMessageCounter() {
    document.getElementById('messageCounter').textContent = `Сообщений: ${messageCounter}`;
}

function formatMessage(content) {
    return content
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>');
}

function showAlert(message, type = '') {
    const container = document.getElementById('alertContainer');
    
    if (!message) {
        container.innerHTML = '';
        return;
    }
    
    const alertClass = type === 'success' ? 'alert-success' : 
                       type === 'error' ? 'alert-error' : 'alert-info';
    
    container.innerHTML = `
        <div class="alert ${alertClass}">
            <span>${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'}</span>
            <span>${message}</span>
        </div>
    `;
}

async function loadTrainingsCount() {
    try {
        const statsResult = await api.request('/auth/stats');
        if (statsResult.success) {
            const trainingsCount = statsResult.trainings_count || 0;
            document.getElementById('messageCounter').textContent = `Сообщений: ${trainingsCount}`;
        }
    } catch (error) {
        // Silently fail - the counter is informational
    }
}
