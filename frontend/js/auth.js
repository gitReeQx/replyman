// ========================================
// ReplyMan AI Assistant - Auth Page Logic
// + Email Verification Support
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    initAuthPage();
});

function initAuthPage() {
    // Check if returning from email verification link
    handleVerificationCallback();
    
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
            // Already logged in — check email verification
            const userResult = await api.getCurrentUser();
            if (userResult.success && userResult.user) {
                if (userResult.user.email_verified) {
                    window.location.href = 'dashboard.html';
                } else {
                    // Logged in but email not verified — show verification screen
                    showVerificationScreen(userResult.user.email);
                }
            }
        }
    } catch (error) {
        // Not logged in, stay on auth page
    }
}

// ========================================
// Login Handler
// ========================================

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
            // Store user info
            localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(result.user));
            
            if (result.user.email_verified) {
                // Email confirmed — redirect to dashboard
                showAlert('Успешный вход! Перенаправление...', 'success');
                setTimeout(() => {
                    window.location.href = 'dashboard.html';
                }, 1000);
            } else {
                // Email NOT confirmed — show verification screen
                showVerificationScreen(email);
            }
        } else {
            showAlert(result.message || 'Ошибка входа', 'error');
        }
    } catch (error) {
        showAlert('Ошибка соединения. Попробуйте позже.', 'error');
    } finally {
        setLoading(submitBtn, false);
    }
}

// ========================================
// Register Handler
// ========================================

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
            // Сохраняем session_token если вернулся (авто-вход после регистрации)
            if (result.session_token) {
                localStorage.setItem(CONFIG.SESSION_KEY, result.session_token);
            }
            
            // Сохраняем данные пользователя
            if (result.user) {
                localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(result.user));
            }
            
            // Показываем экран верификации email
            showVerificationScreen(email);
        } else {
            showAlert(result.message || 'Ошибка регистрации', 'error');
        }
    } catch (error) {
        showAlert('Ошибка соединения. Попробуйте позже.', 'error');
    } finally {
        setLoading(submitBtn, false);
    }
}

// ========================================
// Email Verification Screen
// ========================================

function showVerificationScreen(email) {
    // Hide auth card, show verification card
    document.getElementById('authCard').style.display = 'none';
    document.getElementById('verificationCard').style.display = 'block';
    
    // Set email display
    const emailDisplay = document.getElementById('verificationEmail');
    if (emailDisplay) {
        emailDisplay.textContent = email;
    }
    
    // Set up resend button
    const resendBtn = document.getElementById('resendVerificationBtn');
    if (resendBtn) {
        resendBtn.onclick = handleResendVerification;
    }
    
    // Set up "I already confirmed" button
    const checkBtn = document.getElementById('checkVerificationBtn');
    if (checkBtn) {
        checkBtn.onclick = handleCheckVerification;
    }
    
    // Set up logout button on verification screen
    const logoutBtn = document.getElementById('verificationLogoutBtn');
    if (logoutBtn) {
        logoutBtn.onclick = async () => {
            try {
                await api.logout();
            } catch (e) {}
            localStorage.removeItem(CONFIG.USER_KEY);
            hideVerificationScreen();
        };
    }
}

function hideVerificationScreen() {
    document.getElementById('authCard').style.display = 'flex';
    document.getElementById('verificationCard').style.display = 'none';
}

async function handleResendVerification() {
    const btn = document.getElementById('resendVerificationBtn');
    btn.disabled = true;
    btn.textContent = 'Отправка...';
    
    try {
        const result = await api.sendVerificationEmail();
        if (result.success) {
            showAlertOnVerification('Письмо отправлено! Проверьте почту.', 'success');
            // Disable button for 60 seconds to prevent spam
            let countdown = 60;
            btn.textContent = `Повторить через ${countdown}с`;
            const timer = setInterval(() => {
                countdown--;
                if (countdown <= 0) {
                    clearInterval(timer);
                    btn.disabled = false;
                    btn.textContent = 'Отправить повторно';
                } else {
                    btn.textContent = `Повторить через ${countdown}с`;
                }
            }, 1000);
        } else {
            showAlertOnVerification(result.message || 'Ошибка отправки письма', 'error');
            btn.disabled = false;
            btn.textContent = 'Отправить повторно';
        }
    } catch (error) {
        showAlertOnVerification('Ошибка соединения. Попробуйте позже.', 'error');
        btn.disabled = false;
        btn.textContent = 'Отправить повторно';
    }
}

async function handleCheckVerification() {
    const btn = document.getElementById('checkVerificationBtn');
    btn.disabled = true;
    btn.textContent = 'Проверка...';
    
    try {
        const result = await api.checkEmailVerification();
        if (result.success && result.email_verified) {
            showAlertOnVerification('Email подтверждён! Перенаправление...', 'success');
            setTimeout(() => {
                window.location.href = 'dashboard.html';
            }, 1500);
        } else {
            showAlertOnVerification('Email ещё не подтверждён. Проверьте почту и перейдите по ссылке из письма.', 'error');
            btn.disabled = false;
            btn.textContent = 'Я подтвердил почту';
        }
    } catch (error) {
        showAlertOnVerification('Ошибка проверки. Попробуйте ещё раз.', 'error');
        btn.disabled = false;
        btn.textContent = 'Я подтвердил почту';
    }
}

function showAlertOnVerification(message, type = '') {
    const container = document.getElementById('verificationAlert');
    if (!container) return;
    
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

// ========================================
// Handle Email Verification Callback
// (When user clicks the link from email)
// ========================================

async function handleVerificationCallback() {
    const urlParams = new URLSearchParams(window.location.search);
    const isVerify = urlParams.get('verify');
    const userId = urlParams.get('userId');
    const secret = urlParams.get('secret');
    
    // Clean URL
    if (isVerify || userId || secret) {
        window.history.replaceState({}, document.title, window.location.pathname);
    }
    
    if (userId && secret) {
        // User clicked verification link — confirm it
        showAlert('Подтверждение email...', 'info');
        
        try {
            const result = await api.confirmEmailVerification(userId, secret);
            
            if (result.success) {
                showAlert('Email успешно подтверждён! Теперь вы можете войти.', 'success');
                // If already logged in, redirect to dashboard
                const sessionResult = await api.verifySession();
                if (sessionResult.valid) {
                    setTimeout(() => {
                        window.location.href = 'dashboard.html';
                    }, 2000);
                }
            } else {
                showAlert(result.message || 'Ссылка подтверждения недействительна или устарела.', 'error');
            }
        } catch (error) {
            showAlert('Ошибка подтверждения email. Попробуйте ещё раз.', 'error');
        }
    }
}

// ========================================
// Helper Functions
// ========================================

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
