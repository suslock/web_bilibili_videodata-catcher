// 全局状态
let currentTaskId = null;
let pollInterval = null;

// DOM元素
const elements = {
    keyword: document.getElementById('keyword'),
    maxPages: document.getElementById('maxPages'),
    dateRange: document.getElementsByName('dateRange'),
    sortType: document.getElementById('sortType'),
    startBtn: document.getElementById('startBtn'),
    progressSection: document.getElementById('progressSection'),
    progressFill: document.getElementById('progressFill'),
    progressText: document.getElementById('progressText'),
    progressPercent: document.getElementById('progressPercent'),
    currentPage: document.getElementById('currentPage'),
    totalPages: document.getElementById('totalPages'),
    messageBox: document.getElementById('messageBox'),
    messageContent: document.getElementById('messageContent'),
    previewSection: document.getElementById('previewSection'),
    previewBody: document.getElementById('previewBody'),
    downloadBtn: document.getElementById('downloadBtn'),
    emptyState: document.getElementById('emptyState')
};

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    checkConfig();
});

// 设置事件监听
function setupEventListeners() {
    // 输入验证
    [elements.keyword, elements.maxPages].forEach(input => {
        input.addEventListener('input', validateForm);
    });

    // 单选框
    Array.from(elements.dateRange).forEach(radio => {
        radio.addEventListener('change', validateForm);
    });

    // 下拉框
    elements.sortType.addEventListener('change', validateForm);

    // 开始按钮
    elements.startBtn.addEventListener('click', startSearch);

    // 下载按钮
    elements.downloadBtn.addEventListener('click', downloadExcel);
}

// 验证表单
function validateForm() {
    const keyword = elements.keyword.value.trim();
    const maxPages = parseInt(elements.maxPages.value);
    const dateRange = getSelectedDateRange();
    const sortType = elements.sortType.value;

    const isValid = keyword && maxPages >= 1 && maxPages <= 50 && dateRange && sortType;

    elements.startBtn.disabled = !isValid;
}

// 获取选中的日期范围
function getSelectedDateRange() {
    for (const radio of elements.dateRange) {
        if (radio.checked) return radio.value;
    }
    return null;
}

// 检查配置
async function checkConfig() {
    try {
        const response = await fetch('/api/config/check');
        const data = await response.json();

        if (!data.cookies_configured) {
            showMessage('⚠️ Cookie未配置，请联系管理员设置环境变量', 'error');
        }
    } catch (error) {
        console.error('检查配置失败:', error);
    }
}

// 开始搜索
async function startSearch() {
    const keyword = elements.keyword.value.trim();
    const maxPages = parseInt(elements.maxPages.value);
    const dateRange = getSelectedDateRange();
    const sortType = elements.sortType.value;

    // 重置UI
    resetUI();

    try {
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                keyword,
                max_pages: maxPages,
                date_range: dateRange,
                sort_type: sortType
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '请求失败');
        }

        const data = await response.json();
        currentTaskId = data.task_id;

        // 显示进度条
        elements.progressSection.style.display = 'block';
        elements.progressSection.classList.add('running');
        elements.totalPages.textContent = maxPages;

        // 开始轮询任务状态
        startPolling();

        showMessage('🚀 任务已启动，正在抓取数据...', 'info');

    } catch (error) {
        showMessage(`❌ 启动失败: ${error.message}`, 'error');
    }
}

// 轮询任务状态
function startPolling() {
    pollInterval = setInterval(async () => {
        if (!currentTaskId) return;

        try {
            const response = await fetch(`/api/task/${currentTaskId}`);
            const task = await response.json();

            updateProgress(task);

            if (task.status === 'completed' || task.status === 'failed') {
                stopPolling();
                handleTaskComplete(task);
            }

        } catch (error) {
            console.error('轮询失败:', error);
        }
    }, 2000); // 每2秒轮询一次
}

// 停止轮询
function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
    elements.progressSection.classList.remove('running');
}

// 更新进度
function updateProgress(task) {
    elements.progressFill.style.width = `${task.progress}%`;
    elements.progressPercent.textContent = `${task.progress}%`;
    elements.progressText.textContent = task.message;
    elements.currentPage.textContent = task.current_page;

    if (task.data_preview && task.data_preview.length > 0) {
        updatePreview(task.data_preview);
    }
}

// 更新预览表格
function updatePreview(data) {
    elements.emptyState.style.display = 'none';
    elements.previewSection.style.display = 'block';

    const tbody = elements.previewBody;
    tbody.innerHTML = '';

    data.forEach(row => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td title="${row[0]}">${truncateText(row[0], 30)}</td>
            <td>${row[1]}</td>
            <td>${row[4]}</td>
            <td>${formatNumber(row[5])}</td>
            <td>${formatNumber(row[6])}</td>
        `;
        tbody.appendChild(tr);
    });
}

// 处理任务完成
function handleTaskComplete(task) {
    if (task.status === 'completed') {
        showMessage(`✅ ${task.message}`, 'success');
        elements.downloadBtn.disabled = false;
    } else {
        showMessage(`❌ ${task.message}`, 'error');
    }
}

// 下载Excel
async function downloadExcel() {
    if (!currentTaskId) return;

    try {
        const response = await fetch(`/api/download/${currentTaskId}`);

        if (!response.ok) {
            throw new Error('下载失败');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `bilibili_search_${currentTaskId}.xlsx`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        showMessage('📥 下载成功！', 'success');

    } catch (error) {
        showMessage(`❌ 下载失败: ${error.message}`, 'error');
    }
}

// 显示消息
function showMessage(text, type) {
    elements.messageBox.style.display = 'block';
    elements.messageBox.className = `message-box ${type}`;
    elements.messageContent.textContent = text;

    // 3秒后自动隐藏info消息
    if (type === 'info') {
        setTimeout(() => {
            elements.messageBox.style.display = 'none';
        }, 3000);
    }
}

// 重置UI
function resetUI() {
    elements.progressSection.style.display = 'none';
    elements.messageBox.style.display = 'none';
    elements.previewSection.style.display = 'none';
    elements.emptyState.style.display = 'block';
    elements.downloadBtn.disabled = true;
    elements.progressFill.style.width = '0%';
    currentTaskId = null;
    stopPolling();
}

// 工具函数：截断文本
function truncateText(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

// 工具函数：格式化数字
function formatNumber(num) {
    if (!num || num === 'N/A') return 'N/A';
    const n = parseInt(num);
    if (isNaN(n)) return num;
    if (n >= 10000) {
        return (n / 10000).toFixed(1) + '万';
    }
    return n.toLocaleString();
}

// 页面卸载时清理
window.addEventListener('beforeunload', () => {
    stopPolling();
});