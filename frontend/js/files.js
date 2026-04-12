// ========================================
// ReplyMan AI Assistant - Files Page Logic
// Фоновая обработка с polling-ом статуса
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    initFilesPage();
});

// ID текущего polling-таймера (для отмены при уходе со страницы)
let _pollTimer = null;

async function initFilesPage() {
    await checkAuth();
    initSidebar();
    initFileUpload();
    loadStats();
    loadFileNames();
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

    document.getElementById('refreshStats').addEventListener('click', () => {
        loadStats();
        loadFileNames();
    });
    document.getElementById('clearKnowledge').addEventListener('click', clearKnowledge);
}

// ========================================
// Загрузка файла: быстрый upload → polling статуса
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

    showProgress(5, 'Отправка файла...', `Загрузка ${file.name}`);

    try {
        // === ФАЗА 1: Быстрая отправка файла на сервер ===
        const uploadResult = await uploadFileToServer(file);

        if (!uploadResult.success || !uploadResult.task_id) {
            // Фоллбэк: если сервер вернул старый формат ответа (без task_id)
            if (uploadResult.stage === 'complete') {
                // Старый формат — обработка прошла синхронно
                showProgress(100, 'Готово!', 'Файл успешно обработан');
                setTimeout(() => {
                    showResult(uploadResult);
                    loadStats();
                    loadFileNames();
                }, 500);
                uploadArea.classList.remove('disabled');
                return;
            }
            showAlert(uploadResult.message || 'Ошибка при отправке файла', 'error');
            hideProgress();
            uploadArea.classList.remove('disabled');
            return;
        }

        const taskId = uploadResult.task_id;
        showProgress(5, 'Файл отправлен', 'Сервер начал обработку...');

        // === ФАЗА 2: Polling статуса обработки ===
        await pollTaskStatus(taskId);

    } catch (error) {
        console.error('Upload error:', error);
        showAlert(`Ошибка: ${error.message}`, 'error');
        hideProgress();
    } finally {
        uploadArea.classList.remove('disabled');
    }
}

/**
 * Быстрая отправка файла — возвращает task_id за пару секунд
 */
async function uploadFileToServer(file) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        const formData = new FormData();
        formData.append('file', file);

        // Прогресс загрузки файла на сервер: 0-10%
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 10);
                showProgress(percent, 'Загрузка файла на сервер...',
                    `Отправлено ${formatSize(e.loaded)} из ${formatSize(e.total)}`);
            }
        });

        xhr.addEventListener('load', () => {
            if (xhr.status === 200) {
                try {
                    const result = JSON.parse(xhr.responseText);
                    resolve(result);
                } catch (e) {
                    reject(new Error('Ошибка парсинга ответа сервера'));
                }
            } else if (xhr.status === 0) {
                reject(new Error('Нет связи с сервером'));
            } else {
                reject(new Error(`Ошибка сервера: HTTP ${xhr.status}`));
            }
        });

        xhr.addEventListener('error', () => {
            reject(new Error('Ошибка сети при отправке файла'));
        });

        // Таймаут только на саму загрузку (не на обработку!)
        xhr.timeout = 120000; // 2 минуты на загрузку файла

        const token = localStorage.getItem(CONFIG.SESSION_KEY);
        xhr.open('POST', `${CONFIG.API_BASE_URL}/files/upload`);
        xhr.withCredentials = true;
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);

        xhr.send(formData);
    });
}

/**
 * Опрашивает статус фоновой задачи каждые 2 секунды
 */
function pollTaskStatus(taskId) {
    return new Promise((resolve, reject) => {
        const POLL_INTERVAL = 2000; // 2 секунды
        const MAX_DURATION = 600000; // 10 минут максимум

        const startTime = Date.now();

        // Отменяем предыдущий polling если был
        if (_pollTimer) {
            clearInterval(_pollTimer);
            _pollTimer = null;
        }

        _pollTimer = setInterval(async () => {
            // Проверяем таймаут
            if (Date.now() - startTime > MAX_DURATION) {
                clearInterval(_pollTimer);
                _pollTimer = null;
                reject(new Error('Превышено максимальное время обработки (10 минут)'));
                return;
            }

            try {
                const response = await fetch(
                    `${CONFIG.API_BASE_URL}/files/upload/status/${taskId}`,
                    {
                        headers: {
                            'Authorization': `Bearer ${localStorage.getItem(CONFIG.SESSION_KEY)}`
                        },
                        credentials: 'include'
                    }
                );

                if (!response.ok) {
                    // Если задача не найдена — возможно сервер перезапустился
                    if (response.status === 404) {
                        clearInterval(_pollTimer);
                        _pollTimer = null;
                        reject(new Error('Задача не найдена. Возможно, сервер был перезапущен.'));
                        return;
                    }
                    return; // Пробуем ещё раз на следующей итерации
                }

                const status = await response.json();

                // Обновляем прогресс-бар данными с сервера
                if (status.progress !== undefined) {
                    const stageLabel = status.stage_label || 'Обработка...';
                    const stageDetail = status.stage_detail || '';
                    showProgress(status.progress, stageLabel, stageDetail);
                }

                // Обработка завершена
                if (status.status === 'complete') {
                    clearInterval(_pollTimer);
                    _pollTimer = null;

                    if (status.result) {
                        showProgress(100, 'Готово!', 'Файл успешно обработан');
                        setTimeout(() => {
                            showResult(status.result);
                            loadStats();
                            loadFileNames();
                        }, 500);
                    }
                    resolve(status.result);
                    return;
                }

                // Ошибка обработки
                if (status.status === 'error') {
                    clearInterval(_pollTimer);
                    _pollTimer = null;
                    reject(new Error(status.message || 'Ошибка обработки файла'));
                    return;
                }

                // status === 'processing' — продолжаем ждать

            } catch (error) {
                console.warn('Poll error (will retry):', error);
                // Не прерываем polling при сетовой ошибке — пробуем ещё раз
            }
        }, POLL_INTERVAL);
    });
}

// ========================================
// Прогресс-бар и результаты
// ========================================

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
    fill.classList.remove('indeterminate');
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
        const fill = document.getElementById('progressFill');
        if (fill) {
            fill.classList.remove('indeterminate');
        }
    }
    // Останавливаем polling если активен
    if (_pollTimer) {
        clearInterval(_pollTimer);
        _pollTimer = null;
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
                <div class="value">${formatNumber(result.knowledge_size || 0)}</div>
                <div class="label">Знаний извлечено</div>
            </div>
        </div>
        <button class="btn btn-primary" onclick="resetUploadArea(); loadStats(); loadFileNames();">
            Загрузить ещё файл
        </button>
    `;
}

/**
 * Сбрасывает зону загрузки в исходное состояние, восстанавливая все элементы прогресс-бара
 */
function resetUploadArea() {
    const container = document.getElementById('progressBox');
    if (!container) return;

    container.classList.remove('active');
    container.innerHTML = `
        <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
        <div style="display:flex;justify-content:space-between;font-size:12px">
            <span id="progressPct">0%</span>
            <span id="progressText">Загрузка...</span>
        </div>
        <div class="progress-stage">
            <div class="name" id="stageName">Подготовка</div>
            <div class="detail" id="stageDetail">Ожидание</div>
        </div>
    `;
}

// ========================================
// Список загруженных файлов
// ========================================

async function loadFileNames() {
    const container = document.getElementById('filesList');
    if (!container) return;

    try {
        const result = await api.request('/files/stats');
        if (result.success && result.file_names && result.file_names.length > 0) {
            container.innerHTML = result.file_names.map(name => `
                <div class="file-entry">
                    <div class="file-dot"></div>
                    <div class="file-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<div class="files-list-empty">Файлы ещё не загружены</div>';
        }
    } catch (error) {
        console.error('Failed to load file names:', error);
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ========================================
// Статистика и знания
// ========================================

async function loadStats() {
    try {
        const result = await api.request('/files/stats');
        if (result.success) {
            const sizeEl = document.getElementById('knSize');
            if (sizeEl) sizeEl.textContent = formatNumber(result.knowledge_size || 0);
            
            // Update file count badge in page header
            const badgeEl = document.getElementById('filesCountBadge');
            if (badgeEl && result.file_names) {
                badgeEl.textContent = result.file_names.length;
            }
        }
    } catch (error) {
        console.error('Stats error:', error);
    }
}

async function clearKnowledge() {
    if (!confirm('Удалить всю базу знаний и список загруженных файлов? Это действие необратимо.')) return;

    try {
        const result = await api.request('/files/knowledge', { method: 'DELETE' });
        if (result.success) {
            showAlert('База знаний и список файлов очищены', 'success');
            loadStats();
            loadFileNames();
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

// Останавливаем polling при закрытии страницы
window.addEventListener('beforeunload', () => {
    if (_pollTimer) {
        clearInterval(_pollTimer);
    }
});