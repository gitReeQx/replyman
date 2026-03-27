// ========================================
// ReplyMan AI Assistant - Auth Page Logic
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    initAuthPage();
});

function initAuthPage() {
    // Check if already logged in
    checkSession();
    
    // Form elements
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const showRegisterLink = document.getElementById('showRegister');
    const authSwitch = document.getElementById('authSwitch');
    
    // Toggle forms
    showRegisterLink.addEventListener('click', (e) => {
        e.preventDefault();
        toggleForms();
    });
    
    // Login form submission
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await handleLogin();
    });
    
    // Register form submission
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await handleRegister();
    });
}

function toggleForms() {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const authSwitch = document.getElementById('authSwitch');
    
    loginForm.classList.toggle('hidden');
    registerForm.classList.toggle('hidden');
    
    if (registerForm.classList.contains('hidden')) {
        authSwitch.innerHTML = 'Нет аккаунта? <a href="#" id="showRegister">Зарегистрироваться</a>';
    } else {
        authSwitch.innerHTML = 'Уже есть аккаунт? <a href="#" id="showLogin">Войти</a>';
    }
    
    // Re-attach event listener
    const toggleLink = document.getElementById(registerForm.classList.contains('hidden') ? 'showRegister' : 'showLogin');
    toggleLink.addEventListener('click', (e) => {
        e.preventDefault();
        toggleForms();
    });
    
    // Clear alerts
    showAlert('');
}

async function checkSession() {
    try {
        const result = await api.verifySession();
        if (result.valid) {
            // Already logged in, redirect to dashboard
            window.location.href = 'dashboard.html';
        }
    } catch (error) {
        // Not logged in, stay on auth page
    }
}

async function handleLogin() {
    const email = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPassword').value;
    const submitBtn = document.querySelector('#loginForm button[type="submit"]');
    
    if (!email || !password) {
        showAlert('Пожалуйста, заполните все поля', 'error');
        return;
    }
    
    setLoading(submitBtn, true);
    showAlert('', '');
    
    try {
        const result = await api.login(email, password);
        
        if (result.success) {
            showAlert('Успешный вход! Перенаправление...', 'success');
            
            // Store user info
            localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(result.user));
            
            // Redirect to dashboard
            setTimeout(() => {
                window.location.href = 'dashboard.html';
            }, 1000);
        } else {
            showAlert(result.message || 'Ошибка входа', 'error');
        }
    } catch (error) {
        showAlert('Ошибка соединения. Попробуйте позже.', 'error');
    } finally {
        setLoading(submitBtn, false);
    }
}

async function handleRegister() {
    const name = document.getElementById('registerName').value.trim();
    const email = document.getElementById('registerEmail').value.trim();
    const password = document.getElementById('registerPassword').value;
    const passwordConfirm = document.getElementById('registerPasswordConfirm').value;
    const submitBtn = document.querySelector('#registerForm button[type="submit"]');
    
    // Validation
    if (!email || !password) {
        showAlert('Пожалуйста, заполните обязательные поля', 'error');
        return;
    }
    
    if (password.length < 8) {
        showAlert('Пароль должен содержать минимум 8 символов', 'error');
        return;
    }
    
    if (password !== passwordConfirm) {
        showAlert('Пароли не совпадают', 'error');
        return;
    }
    
    setLoading(submitBtn, true);
    showAlert('', '');
    
    try {
        const result = await api.register(email, password, name || null);
        
        if (result.success) {
            showAlert('Регистрация успешна! Теперь вы можете войти.', 'success');
            
            // Clear form and switch to login
            document.getElementById('registerForm').reset();
            setTimeout(() => {
                toggleForms();
            }, 1500);
        } else {
            showAlert(result.message || 'Ошибка регистрации', 'error');
        }
    } catch (error) {
        showAlert('Ошибка соединения. Попробуйте позже.', 'error');
    } finally {
        setLoading(submitBtn, false);
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
}

function setLoading(button, isLoading) {
    if (isLoading) {
        button.disabled = true;
        button.dataset.originalText = button.innerHTML;
        button.innerHTML = '<span class="spinner" style="width: 20px; height: 20px; border-width: 2px;"></span>';
    } else {
        button.disabled = false;
        button.innerHTML = button.dataset.originalText || button.innerHTML;
    }
}
