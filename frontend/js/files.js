// ========================================
// ReplyMan AI Assistant - Files Page Logic
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    initFilesPage();
});

async function initFilesPage() {
    // Check authentication
    await checkAuth();
    
    // Initialize components
    initSidebar();
    initFileUpload();
    loadFiles();
    
    // Load context button
    document.getElementById('loadContext').addEventListener('click', loadContext);
    
    // Refresh files button
    document.getElementById('refreshFiles').addEventListener('click', loadFiles);
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
    
    // Click to upload
    uploadArea.addEventListener('click', () => {
        fileInput.click();
    });
    
    // File selection
    fileInput.addEventListener('change', handleFileSelect);
    
    // Drag and drop
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
        
        const files = e.dataTransfer.files;
        handleFiles(files);
    });
}

function handleFileSelect(e) {
    const files = e.target.files;
    handleFiles(files);
    e.target.value = ''; // Reset input
}

async function handleFiles(files) {
    for (const file of files) {
        await uploadFile(file);
    }
    loadFiles();
}

async function uploadFile(file) {
    // Validate file
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    
    if (!CONFIG.ALLOWED_EXTENSIONS.includes(ext)) {
        showAlert(`Неподдерживаемый формат файла: ${file.name}`, 'error');
        return;
    }
    
    if (file.size > CONFIG.MAX_FILE_SIZE) {
        showAlert(`Файл слишком большой: ${file.name} (макс. 30MB)`, 'error');
        return;
    }
    
    showAlert(`Загрузка: ${file.name}...`, 'info');
    
    try {
        const result = await api.uploadFile(file, (progress) => {
            // Could show progress here
        });
        
        if (result.success) {
            showAlert(`Файл "${file.name}" успешно загружен`, 'success');
        } else {
            showAlert(`Ошибка загрузки: ${result.message}`, 'error');
        }
    } catch (error) {
        showAlert(`Ошибка загрузки файла: ${error.message}`, 'error');
    }
}

async function loadFiles() {
    const filesLoading = document.getElementById('filesLoading');
    const filesList = document.getElementById('filesList');
    const emptyFiles = document.getElementById('emptyFiles');
    
    filesLoading.style.display = 'flex';
    filesList.style.display = 'none';
    emptyFiles.classList.add('hidden');
    
    try {
        const result = await api.getFiles();
        
        filesLoading.style.display = 'none';
        
        if (result.success && result.files.length > 0) {
            filesList.style.display = 'flex';
            renderFiles(result.files);
        } else {
            emptyFiles.classList.remove('hidden');
        }
        
        // Update stats
        const statsFilesCount = parent.document.getElementById('filesCount');
        if (statsFilesCount) {
            statsFilesCount.textContent = result.files?.length || 0;
        }
        
    } catch (error) {
        filesLoading.style.display = 'none';
        emptyFiles.classList.remove('hidden');
        showAlert('Ошибка загрузки списка файлов', 'error');
    }
}

function renderFiles(files) {
    const filesList = document.getElementById('filesList');
    filesList.innerHTML = '';
    
    files.forEach(file => {
        const fileItem = document.createElement('div');
        fileItem.className = 'file-item';
        
        const icon = getFileIcon(file.name);
        const size = formatFileSize(file.size);
        const date = new Date(file.uploaded_at).toLocaleDateString('ru-RU');
        
        fileItem.innerHTML = `
            <div class="file-icon">${icon}</div>
            <div class="file-info">
                <div class="file-name">${file.name}</div>
                <div class="file-meta">${size} • ${date}</div>
            </div>
            <div class="file-actions">
                <button class="btn btn-secondary btn-sm" onclick="viewFile('${file.id}')" title="Просмотр">
                    👁️
                </button>
                <button class="btn btn-danger btn-sm" onclick="deleteFile('${file.id}')" title="Удалить">
                    🗑️
                </button>
            </div>
        `;
        
        filesList.appendChild(fileItem);
    });
}

function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        'txt': '📄',
        'json': '📋',
        'html': '🌐',
        'htm': '🌐'
    };
    return icons[ext] || '📁';
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

async function viewFile(fileId) {
    try {
        const result = await api.getFileContent(fileId);
        
        if (result.success) {
            const contextContainer = document.getElementById('contextContainer');
            contextContainer.innerHTML = `
                <h4 style="margin-bottom: 15px;">Содержимое файла:</h4>
                <div style="background: var(--bg-primary); padding: 20px; border-radius: var(--border-radius-sm); white-space: pre-wrap; max-height: 400px; overflow-y: auto;">
${escapeHtml(result.content)}
                </div>
            `;
            
            // Scroll to context
            contextContainer.scrollIntoView({ behavior: 'smooth' });
        }
    } catch (error) {
        showAlert('Ошибка при загрузке содержимого файла', 'error');
    }
}

async function deleteFile(fileId) {
    if (!confirm('Удалить этот файл?')) return;
    
    try {
        const result = await api.deleteFile(fileId);
        
        if (result.success) {
            showAlert('Файл удален', 'success');
            loadFiles();
        } else {
            showAlert('Ошибка удаления файла', 'error');
        }
    } catch (error) {
        showAlert('Ошибка удаления файла', 'error');
    }
}

async function loadContext() {
    const contextContainer = document.getElementById('contextContainer');
    contextContainer.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    
    try {
        const result = await api.getContext();
        
        if (result.success && result.context) {
            const preview = result.context.substring(0, 5000);
            const remaining = result.context.length > 5000 ? `... и ещё ${result.context.length - 5000} символов` : '';
            
            contextContainer.innerHTML = `
                <div class="alert alert-info mb-20">
                    Всего файлов: ${result.files_count} • Общий объем: ${result.context.length} символов
                </div>
                <div style="background: var(--bg-primary); padding: 20px; border-radius: var(--border-radius-sm); white-space: pre-wrap; max-height: 500px; overflow-y: auto;">
${escapeHtml(preview)}
${remaining}
                </div>
            `;
        } else {
            contextContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📭</div>
                    <div class="empty-title">Нет данных</div>
                    <div class="empty-desc">Загрузите файлы для формирования контекста</div>
                </div>
            `;
        }
    } catch (error) {
        contextContainer.innerHTML = `
            <div class="alert alert-error">
                Ошибка загрузки контекста
            </div>
        `;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
