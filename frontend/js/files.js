// ========================================
// ReplyMan AI Assistant - Files Page Logic
// Исправленная версия с корректными ID элементов
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    initFilesPage();
});

async function initFilesPage() {
    await checkAuth();
    initSidebar();
    initFileUpload();
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

function initFileUpload() {
    const uploadArea = document.getElementById('fileUploadArea');
    const fileInput = document.getElementById('fileInput');
    
    uploadArea.addEventListener('click', () => {
        if (!uploadArea.classList.contains('disabled')) {
            fileInput.click();
        }
    });
    
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFile(e.target.files[0]);
        }
        e.target.value = '';
    });
    
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });
    
    uploadArea.addEventListener('dragleave', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
    });
    
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleFile(e.dataTransfer.files[0]);
        }
    });
    
    document.getElementById('refreshStats').addEventListener('click', loadStats);
    document.getElementById('showKnowledge').addEventListener('click', showKnowledge);
    document.getElementById('clearKnowledge').addEventListener('click', clearKnowledge);
}

// ========================================
// Загрузка файла с прогрессом
// ========================================

async function handleFile(file) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    const allowed = ['.txt', '.json', '.html', '.htm', '.pdf', '.docx', '.doc'];
    
    if (!allowed.includes(ext)) {
        showAlert(`Неподдерживаемый формат. Разрешены: ${allowed.join(', ')}`, 'error');
        return;
    }
    
    if (file.size > 30 * 1024 * 1024) {
        showAlert('Файл слишком большой. Максимум: 30MB', 'error');
        return;
    }
    
    const uploadArea = document.getElementById('fileUploadArea');
    uploadArea.classList.add('disabled');
    
    showProgress(0, 'Загрузка файла...', 'Подготовка к отправке');
    
    try {
        const result = await uploadWithProgress(file);
        
        if (result.success) {
            showResult(result);
            loadStats(); // обновляем статистику после загрузки
        } else {
            showAlert(result.message || 'Ошибка обработки', 'error');
            hideProgress();
        }
    } catch (error) {
        console.error('Upload error:', error);
        showAlert(`Ошибка: ${error.message}`, 'error');
        hideProgress();
    } finally {
        uploadArea.classList.remove('disabled');
    }
}

async function uploadWithProgress(file) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        const formData = new FormData();
        formData.append('file', file);
        
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 50);
                showProgress(percent, 'Загрузка файла...', `Отправлено ${formatSize(e.loaded)} из ${formatSize(e.total)}`);
            }
        });
        
        xhr.addEventListener('load', () => {
            if (xhr.status === 200) {
                try {
                    const result = JSON.parse(xhr.responseText);
                    if (result.success) {
                        showProgress(65, 'Оптимизация...', `Сжатие: ${result.compression || 0}%`);
                        setTimeout(() => {
                            showProgress(85, 'AI-анализ...', `Извлечено знаний: ${result.knowledge_size || 0} символов`);
                            setTimeout(() => {
                                resolve(result);
                            }, 300);
                        }, 300);
                    } else {
                        resolve(result);
                    }
                } catch (e) {
                    reject(new Error('Ошибка парсинга ответа'));
                }
            } else {
                reject(new Error(`HTTP ${xhr.status}`));
            }
        });
        
        xhr.addEventListener('error', () => reject(new Error('Ошибка сети')));
        xhr.addEventListener('timeout', () => reject(new Error('Таймаут')));
        xhr.timeout = 300000;
        
        const token = localStorage.getItem(CONFIG.SESSION_KEY);
        xhr.open('POST', `${CONFIG.API_BASE_URL}/files/upload`);
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        xhr.send(formData);
    });
}

function showProgress(percent, stage, detail) {
    const container = document.getElementById('progressBox');
    const fill = document.getElementById('progressFill');
    const pctEl = document.getElementById('progressPct');
    const textEl = document.getElementById('progressText');
    const stageName = document.getElementById('stageName');
    const stageDetail = document.getElementById('stageDetail');
    
    if (!container || !fill || !pctEl || !textEl || !stageName || !stageDetail) return;
    
    container.classList.add('active');
    fill.style.width = `${percent}%`;
    pctEl.textContent = `${percent}%`;
    
    if (stage) {
        stageName.textContent = stage;
    }
    if (detail !== undefined) {
        stageDetail.textContent = detail;
    }
    textEl.textContent = stage || '';
}

function hideProgress() {
    const container = document.getElementById('progressBox');
    if (container) {
        container.classList.remove('active');
    }
}

function showResult(result) {
    const container = document.getElementById('progressBox');
    if (!container) return;
    
    container.innerHTML = `
        <div class="alert alert-success" style="margin-bottom: 15px;">
            ✅ Файл успешно обработан!
        </div>
        <div class="stats-row">
            <div class="stat-item">
                <div class="value">${formatSize(result.original_size || 0)}</div>
                <div class="label">Исходный размер</div>
            </div>
            <div class="stat-item">
                <div class="value">${result.compression || 0}%</div>
                <div class="label">Сжатие</div>
            </div>
            <div class="stat-item">
                <div class="value">${result.knowledge_size || 0}</div>
                <div class="label">Знаний извлечено</div>
            </div>
        </div>
        <button class="btn btn-primary" onclick="this.parentElement.innerHTML=''; loadStats();">
            Загрузить ещё файл
        </button>
    `;
}

// ========================================
// Статистика и знания
// ========================================

async function loadStats() {
    try {
        const result = await api.request('/files/stats');
        if (result.success) {
            const sizeEl = document.getElementById('knSize');
            const tokensEl = document.getElementById('knTokens');
            if (sizeEl) sizeEl.textContent = formatNumber(result.knowledge_size || 0);
            if (tokensEl) tokensEl.textContent = formatNumber(result.knowledge_tokens || 0);
        }
    } catch (error) {
        console.error('Stats error:', error);
    }
}

async function showKnowledge() {
    const preview = document.getElementById('preview');
    const content = document.getElementById('previewContent');
    
    if (!preview || !content) return;
    
    preview.style.display = 'block';
    content.textContent = 'Загрузка...';
    
    try {
        const result = await api.request('/files/knowledge');
        if (result.success) {
            content.textContent = result.knowledge || '(пусто)';
        } else {
            content.textContent = 'Ошибка: ' + (result.message || 'Unknown');
        }
    } catch (error) {
        content.textContent = 'Ошибка загрузки: ' + error.message;
    }
}

async function clearKnowledge() {
    if (!confirm('Удалить всю базу знаний? Это действие необратимо.')) return;
    
    try {
        const result = await api.request('/files/knowledge', { method: 'DELETE' });
        if (result.success) {
            showAlert('База знаний очищена', 'success');
            const preview = document.getElementById('preview');
            if (preview) preview.style.display = 'none';
            loadStats();
        } else {
            showAlert('Ошибка: ' + (result.message || 'Unknown'), 'error');
        }
    } catch (error) {
        showAlert('Ошибка: ' + error.message, 'error');
    }
}

// ========================================
// Вспомогательные функции
// ========================================

function formatSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatNumber(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

function showAlert(message, type = '') {
    const container = document.getElementById('alertContainer');
    if (!container) return;
    
    const alertClass = type === 'success' ? 'alert-success' : 
                       type === 'error' ? 'alert-error' : 'alert-info';
    
    container.innerHTML = `
        <div class="alert ${alertClass}">
            <span>${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'}</span>
            <span>${message}</span>
        </div>
    `;
    
    if (type === 'success') {
        setTimeout(() => {
            container.innerHTML = '';
        }, 3000);
    }
}