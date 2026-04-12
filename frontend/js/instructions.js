// ========================================
// ReplyMan AI Assistant - Instructions Page Logic
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    initInstructionsPage();
});

async function initInstructionsPage() {
    // Check authentication
    await checkAuth();
    
    // Initialize components
    initSidebar();
    initInstructionsEditor();
    loadInstructions();
}

async function checkAuth() {
    try {
        const result = await api.getCurrentUser();
        if (result.success && result.user) {
            // Проверяем подтверждение email
            if (!result.user.email_verified) {
                window.location.href = 'index.html';
                return;
            }
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

function initInstructionsEditor() {
    const textarea = document.getElementById('instructionsTextarea');
    const charCounter = document.getElementById('charCounter');
    const saveBtn = document.getElementById('saveInstructions');
    const resetBtn = document.getElementById('resetInstructions');
    
    // Character counter
    textarea.addEventListener('input', () => {
        const count = textarea.value.length;
        charCounter.textContent = `${count} символов`;
    });
    
    // Save instructions
    saveBtn.addEventListener('click', saveInstructions);
    
    // Reset instructions
    resetBtn.addEventListener('click', async () => {
        if (confirm('Сбросить инструкции к настройкам по умолчанию?')) {
            try {
                await api.resetInstructions();
                textarea.value = '';
                charCounter.textContent = '0 символов';
                showAlert('Инструкции сброшены', 'success');
            } catch (error) {
                showAlert('Ошибка сброса инструкций', 'error');
            }
        }
    });
}

async function loadInstructions() {
    try {
        const result = await api.getInstructions();
        
        if (result.success) {
            const textarea = document.getElementById('instructionsTextarea');
            textarea.value = result.instructions || '';
            
            // Update counter
            const charCounter = document.getElementById('charCounter');
            charCounter.textContent = `${textarea.value.length} символов`;
        }
    } catch (error) {
        console.error('Failed to load instructions:', error);
    }
}

async function saveInstructions() {
    const textarea = document.getElementById('instructionsTextarea');
    const saveBtn = document.getElementById('saveInstructions');
    const instructions = textarea.value.trim();
    
    saveBtn.disabled = true;
    saveBtn.innerHTML = 'Сохранение...';
    
    try {
        const result = await api.saveInstructions(instructions);
        
        if (result.success) {
            showAlert('Инструкции успешно сохранены', 'success');
        } else {
            showAlert(result.message || 'Ошибка сохранения', 'error');
        }
    } catch (error) {
        showAlert('Ошибка соединения', 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '💾 Сохранить инструкции';
    }
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
    
    // Auto-hide success messages
    if (type === 'success') {
        setTimeout(() => {
            container.innerHTML = '';
        }, 3000);
    }
}
