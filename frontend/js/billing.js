// ========================================
// ReplyMan AI Assistant - Billing Page Logic
// Оплата тарифов через ЮKassa
// ========================================

let currentPlan = null;
let selectedTariff = null;
let selectedPeriod = 'monthly'; // 'monthly' | 'yearly'

document.addEventListener('DOMContentLoaded', () => {
    initBilling();
});

async function initBilling() {
    await checkAuth();
    initSidebar();
    loadSubscription();
    loadTariffs();
    loadPaymentHistory();
    checkPaymentResult();
}

// ========================================
// Auth & Sidebar
// ========================================

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

// ========================================
// Period Toggle
// ========================================

function switchPeriod(period) {
    selectedPeriod = period;
    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.period === period);
    });
    renderTariffs(lastTariffsData);
}

// ========================================
// Subscription Status
// ========================================

async function loadSubscription() {
    try {
        const result = await api.getSubscription();
        if (result.success) {
            currentPlan = result.subscription;
            renderPlanStatus(result.subscription);
        } else {
            renderPlanStatus(null);
        }
    } catch (error) {
        console.error('Failed to load subscription:', error);
        renderPlanStatus(null);
    }
}

function renderPlanStatus(sub) {
    const statusEl = document.getElementById('planStatus');
    const iconEl = document.getElementById('statusIcon');
    const titleEl = document.getElementById('statusTitle');
    const subtitleEl = document.getElementById('statusSubtitle');
    const tariffEl = document.getElementById('detailTariff');
    const payDateEl = document.getElementById('detailPayDate');
    const expiryEl = document.getElementById('detailExpiry');
    const requestsEl = document.getElementById('detailRequests');

    if (!sub || sub.subscription_type === 'бесплатный' || sub.subscription_status === 'inactive') {
        statusEl.className = 'plan-status inactive';
        iconEl.textContent = '🆓';
        titleEl.textContent = 'Бесплатный тариф';
        subtitleEl.textContent = 'Ограниченный функционал. Оплатите тариф, чтобы получить больше возможностей.';
        tariffEl.textContent = 'Бесплатный';
        payDateEl.textContent = '—';
        expiryEl.textContent = '—';
        const reqs = sub?.daily_requests_count || 0;
        requestsEl.textContent = `${reqs} / 3 в день`;
    } else if (sub.subscription_status === 'active') {
        statusEl.className = 'plan-status active';
        iconEl.textContent = '✅';
        titleEl.textContent = getTariffDisplayName(sub.subscription_type);
        
        if (sub.subscription_type === 'старт') {
            subtitleEl.textContent = 'Тариф активен. Доступно до 20 запросов в день.';
            const reqs = sub?.daily_requests_count || 0;
            requestsEl.textContent = `${reqs} / 20 в день`;
        } else {
            subtitleEl.textContent = 'Тариф активен. Без ограничений по запросам + тренажёр.';
            requestsEl.textContent = 'Без ограничений';
        }
        
        tariffEl.textContent = getTariffDisplayName(sub.subscription_type);
        payDateEl.textContent = formatDate(sub.subscription_paid_at);
        expiryEl.textContent = formatDate(sub.subscription_expires_at);
    } else if (sub.subscription_status === 'expired') {
        statusEl.className = 'plan-status expired';
        iconEl.textContent = '⚠️';
        titleEl.textContent = 'Тариф истёк';
        subtitleEl.textContent = 'Срок действия тарифа закончился. Оплатите снова, чтобы продолжить.';
        tariffEl.textContent = getTariffDisplayName(sub.subscription_type);
        payDateEl.textContent = formatDate(sub.subscription_paid_at);
        expiryEl.textContent = formatDate(sub.subscription_expires_at);
        requestsEl.textContent = '0 / 3 в день';
    }
}

// ========================================
// Tariffs
// ========================================

let lastTariffsData = null;

async function loadTariffs() {
    try {
        const result = await api.getTariffs();
        if (result.success && result.tariffs) {
            lastTariffsData = result.tariffs;
            renderTariffs(result.tariffs);
        } else {
            document.getElementById('tariffsGrid').innerHTML = `
                <div class="history-empty" style="grid-column: 1 / -1;">
                    <div class="history-empty-icon">😕</div>
                    <p>Не удалось загрузить тарифы</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('Failed to load tariffs:', error);
    }
}

function renderTariffs(tariffs) {
    if (!tariffs) return;
    const grid = document.getElementById('tariffsGrid');
    const currentType = currentPlan?.subscription_type || 'бесплатный';
    const isActive = currentPlan?.subscription_status === 'active';

    grid.innerHTML = tariffs.map(tariff => {
        const isCurrent = tariff.id === currentType && isActive;
        const isRecommended = tariff.recommended || false;
        const isFree = tariff.id === 'бесплатный';
        
        // Цена в зависимости от периода
        const price = selectedPeriod === 'yearly' ? tariff.price_yearly : tariff.price_monthly;
        const periodLabel = selectedPeriod === 'yearly' ? '/ год' : '/ мес';
        
        const featuresHtml = tariff.features.map(f => {
            if (f.included) {
                return `<li><span class="check">✓</span> ${f.text}</li>`;
            } else {
                return `<li><span class="cross">✗</span> <span style="opacity:0.5">${f.text}</span></li>`;
            }
        }).join('');

        let btnHtml;
        if (isCurrent) {
            btnHtml = `<button class="tariff-btn btn-current" disabled>Текущий тариф</button>`;
        } else if (isFree) {
            btnHtml = `<button class="tariff-btn btn-free" disabled>Бесплатный</button>`;
        } else {
            btnHtml = `<button class="tariff-btn btn-select" data-tariff="${tariff.id}" onclick="selectTariff('${tariff.id}')">Оплатить</button>`;
        }

        // Годовая инфа
        let yearlyInfo = '';
        if (!isFree && selectedPeriod === 'yearly' && tariff.price_yearly_old) {
            yearlyInfo = `<div class="tariff-yearly-info"><span class="old-price">${tariff.price_yearly_old.toLocaleString('ru-RU')} ₽</span> ${tariff.price_yearly.toLocaleString('ru-RU')} ₽ за год — экономия ${tariff.yearly_save.toLocaleString('ru-RU')} ₽</div>`;
        } else if (!isFree) {
            yearlyInfo = `<div style="font-size:0.8rem; color:var(--text-secondary); margin-bottom:18px;">При оплате за год — скидка 15%</div>`;
        }

        return `
            <div class="tariff-card ${isCurrent ? 'current' : ''} ${isRecommended ? 'recommended' : ''}">
                <div class="tariff-name">${tariff.name}</div>
                <div class="tariff-desc">${tariff.description}</div>
                <div class="tariff-price">
                    ${isFree 
                        ? '<span class="amount">Бесплатно</span>' 
                        : `<span class="amount">${price.toLocaleString('ru-RU')}</span><span class="currency">₽</span><span class="period">${periodLabel}</span>`
                    }
                </div>
                ${yearlyInfo}
                <ul class="tariff-features">${featuresHtml}</ul>
                ${btnHtml}
            </div>
        `;
    }).join('');
}

function selectTariff(tariffId) {
    selectedTariff = tariffId;
    showPaymentModal(tariffId);
}

// ========================================
// Payment Modal
// ========================================

function showPaymentModal(tariffId) {
    if (!lastTariffsData) return;
    const tariff = lastTariffsData.find(t => t.id === tariffId);
    if (!tariff) return;

    const price = selectedPeriod === 'yearly' ? tariff.price_yearly : tariff.price_monthly;
    const periodLabel = selectedPeriod === 'yearly' ? 'за год' : 'за месяц';

    document.getElementById('modalTariffName').textContent = tariff.name;
    document.getElementById('modalTariffPeriod').textContent = `Период: ${periodLabel}`;
    document.getElementById('modalTariffPrice').textContent = `${price.toLocaleString('ru-RU')} ₽`;

    const overlay = document.getElementById('paymentOverlay');
    overlay.classList.add('active');
}

function hidePaymentModal() {
    document.getElementById('paymentOverlay').classList.remove('active');
    selectedTariff = null;
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('modalCancel').addEventListener('click', hidePaymentModal);
    document.getElementById('modalConfirm').addEventListener('click', initiatePayment);
    
    document.getElementById('paymentOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) hidePaymentModal();
    });
});

async function initiatePayment() {
    if (!selectedTariff) return;
    
    const confirmBtn = document.getElementById('modalConfirm');
    const cancelBtn = document.getElementById('modalCancel');
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Создаём платёж...';
    cancelBtn.disabled = true;

    try {
        const result = await api.createPayment(selectedTariff, selectedPeriod);
        
        if (result.success && result.confirmation_url) {
            window.location.href = result.confirmation_url;
        } else {
            showAlert('error', result.message || 'Ошибка при создании платежа');
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Перейти к оплате';
            cancelBtn.disabled = false;
        }
    } catch (error) {
        console.error('Payment creation error:', error);
        showAlert('error', 'Не удалось создать платёж. Попробуйте позже.');
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Перейти к оплате';
        cancelBtn.disabled = false;
    }
}

// ========================================
// Payment History
// ========================================

async function loadPaymentHistory() {
    try {
        const result = await api.getPaymentHistory();
        if (result.success && result.payments && result.payments.length > 0) {
            renderPaymentHistory(result.payments);
        } else {
            document.getElementById('paymentHistory').innerHTML = `
                <div class="history-empty">
                    <div class="history-empty-icon">📄</div>
                    <p>История платежей пуста</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('Failed to load payment history:', error);
    }
}

function renderPaymentHistory(payments) {
    const container = document.getElementById('paymentHistory');
    
    container.innerHTML = payments.map(payment => {
        const statusClass = payment.status === 'succeeded' ? 'success' : 
                           payment.status === 'pending' || payment.status === 'waiting_for_capture' ? 'pending' : 'failed';
        const statusText = payment.status === 'succeeded' ? 'Оплачено' : 
                          payment.status === 'pending' || payment.status === 'waiting_for_capture' ? 'В обработке' : 
                          payment.status === 'canceled' ? 'Отменено' : 'Ошибка';
        const statusIcon = statusClass === 'success' ? '✅' : statusClass === 'pending' ? '⏳' : '❌';

        return `
            <div class="payment-item">
                <div class="payment-info">
                    <div class="payment-icon ${statusClass}">${statusIcon}</div>
                    <div class="payment-details">
                        <div class="payment-tariff">${getTariffDisplayName(payment.tariff_id || payment.description || '—')}</div>
                        <div class="payment-date">${formatDate(payment.created_at)}</div>
                    </div>
                </div>
                <div>
                    <span class="payment-amount ${statusClass}">${payment.amount?.toLocaleString('ru-RU') || '—'} ₽</span>
                    <span class="payment-status-badge ${statusClass}">${statusText}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ========================================
// Check Payment Result
// ========================================

function checkPaymentResult() {
    const urlParams = new URLSearchParams(window.location.search);
    const paymentParam = urlParams.get('payment');
    const paymentId = urlParams.get('payment_id');
    
    // Очищаем URL от параметров сразу
    window.history.replaceState({}, document.title, window.location.pathname);
    
    if (paymentParam === 'pending' && paymentId) {
        // Пользователь вернулся с YooKassa — проверяем реальный статус платежа
        showAlert('info', 'Проверяем статус оплаты...');
        verifyPaymentStatus(paymentId);
    }
}

async function verifyPaymentStatus(paymentId) {
    try {
        // Небольшая задержка — вебхук от YooKassa может прийти с задержкой
        await new Promise(resolve => setTimeout(resolve, 1500));
        
        const result = await api.checkPaymentStatus(paymentId);
        
        if (result.success) {
            if (result.status === 'succeeded') {
                showAlert('success', 'Оплата прошла успешно! Ваш тариф активирован.');
                // Обновляем все данные на странице
                loadSubscription();
                loadTariffs();
                loadPaymentHistory();
            } else if (result.status === 'pending' || result.status === 'waiting_for_capture') {
                showAlert('info', 'Оплата ещё обрабатывается. Статус обновится автоматически.');
                // Проверим ещё раз через 5 секунд
                setTimeout(() => verifyPaymentStatus(paymentId), 5000);
            } else if (result.status === 'canceled') {
                showAlert('warning', 'Оплата была отменена. Вы можете попробовать ещё раз.');
                loadPaymentHistory();
            } else {
                showAlert('warning', `Статус оплаты: ${result.status}. Обновите страницу позже.`);
                loadPaymentHistory();
            }
        } else {
            // Не удалось проверить через API — проверяем подписку
            const subResult = await api.getSubscription();
            if (subResult.success && subResult.subscription?.subscription_status === 'active' && subResult.subscription?.subscription_type !== 'бесплатный') {
                showAlert('success', 'Оплата прошла успешно! Ваш тариф активирован.');
                loadSubscription();
                loadTariffs();
                loadPaymentHistory();
            } else {
                showAlert('info', 'Не удалось проверить статус оплаты. Обновите страницу.');
            }
        }
    } catch (error) {
        console.error('Payment status check error:', error);
        // Fallback — проверяем подписку
        try {
            const subResult = await api.getSubscription();
            if (subResult.success && subResult.subscription?.subscription_status === 'active' && subResult.subscription?.subscription_type !== 'бесплатный') {
                showAlert('success', 'Оплата прошла успешно! Ваш тариф активирован.');
                loadSubscription();
                loadTariffs();
                loadPaymentHistory();
            } else {
                showAlert('info', 'Не удалось проверить статус оплаты. Обновите страницу позже.');
            }
        } catch {
            showAlert('info', 'Не удалось проверить статус оплаты. Обновите страницу позже.');
        }
    }
}

// ========================================
// Helpers
// ========================================

function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString('ru-RU', {
            day: '2-digit',
            month: 'long',
            year: 'numeric'
        });
    } catch {
        return dateStr;
    }
}

function getTariffDisplayName(tariffId) {
    const names = {
        'бесплатный': 'Бесплатный',
        'free': 'Бесплатный',
        'старт': 'Старт',
        'start': 'Старт',
        'бизнес': 'Бизнес',
        'business': 'Бизнес',
    };
    return names[tariffId] || tariffId || '—';
}

function showAlert(type, message) {
    const container = document.getElementById('alertContainer');
    const alertEl = document.createElement('div');
    alertEl.className = `alert alert-${type}`;
    alertEl.innerHTML = `
        <span>${type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️'}</span>
        <span>${message}</span>
    `;
    container.appendChild(alertEl);
    
    setTimeout(() => {
        alertEl.style.opacity = '0';
        alertEl.style.transition = 'opacity 0.3s';
        setTimeout(() => alertEl.remove(), 300);
    }, 5000);
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('refreshHistory').addEventListener('click', loadPaymentHistory);
});
