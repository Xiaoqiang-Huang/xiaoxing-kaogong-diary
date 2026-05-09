/**
 * 日记系统前端核心逻辑
 */

// ==================== 工具函数 ====================

/**
 * 添加消息到对话区域
 * @param role 消息角色
 * @param content 消息内容
 * @param sources 可选，数据来源 [{id, date}, ...]
 * @param scroll 是否滚动到底部
 * @param images 可选，图片URL数组
 */
function appendMessage(role, content, sources = null, scroll = true, images = null) {
    const messagesDiv = document.getElementById('messages');
    if (!messagesDiv) return null;

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    // 处理内容格式
    let formattedContent = formatContent(content);

    // 如果有图片，添加图片HTML
    if (images && images.length > 0) {
        console.log('[appendMessage] 添加图片:', images);
        const imagesHtml = images.map(url =>
            `<img src="${url}" alt="图片" style="max-width: 100%; height: auto; border-radius: 4px; margin: 8px 0; display: block;">`
        ).join('');
        formattedContent = formattedContent + imagesHtml;
    }

    let html = `<div class="message-content">${formattedContent}`;

    // 如果有数据来源，添加来源链接
    if (sources && sources.length > 0) {
        html += `<div class="message-sources">📚 来源: `;
        html += sources.slice(0, 3).map(s => `<a href="#" onclick="viewDiary(${s.id}); return false;">${s.date}</a>`).join(', ');
        if (sources.length > 3) {
            html += ` 等${sources.length}篇`;
        }
        html += `</div>`;
    }

    html += `</div>`;

    messageDiv.innerHTML = html;
    messagesDiv.appendChild(messageDiv);

    if (scroll) {
        scrollMessagesToBottom(messagesDiv, messageDiv);
    }

    return messageDiv;
}

function getPublicAppendMessage() {
    return window.DiaryApp?.appendMessage || appendMessage;
}

function scrollMessagesToBottom(messagesDiv = document.getElementById('messages'), target = null, options = {}) {
    if (!messagesDiv) return;
    const behavior = options.smooth ? 'smooth' : 'auto';

    const scroll = () => {
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        if (target && target.scrollIntoView) {
            target.scrollIntoView({ block: 'end', behavior });
        }
    };

    scroll();
    requestAnimationFrame(scroll);
    setTimeout(scroll, 120);
    setTimeout(scroll, 320);
}

function assistantReplyVisible(reply) {
    if (!reply) return true;
    const probe = String(reply).trim().slice(0, 24);
    if (!probe) return true;

    return Array.from(document.querySelectorAll('.message.assistant:not(.loading-message) .message-content'))
        .some(el => (el.textContent || '').includes(probe));
}

async function reconcileConversationIfNeeded(expectedReply = '') {
    const messagesDiv = document.getElementById('messages');
    if (!messagesDiv || assistantReplyVisible(expectedReply)) {
        scrollMessagesToBottom(messagesDiv);
        return;
    }

    try {
        const response = await fetch('/api/conversation?limit=10', { cache: 'no-store' });
        if (!response.ok) return;

        const data = await response.json();
        if (!data.messages || data.messages.length === 0) return;

        messagesDiv.innerHTML = '';
        const append = getPublicAppendMessage();
        data.messages.forEach(msg => append(msg.role, msg.content, null, false));
        scrollMessagesToBottom(messagesDiv, messagesDiv.lastElementChild);
    } catch (error) {
        console.warn('对话回拉失败:', error);
    }
}

/**
 * 格式化消息内容 - 支持Markdown渲染
 */
function formatContent(content) {
    // 如果marked.js可用，使用markdown渲染
    if (typeof marked !== 'undefined') {
        try {
            // 配置marked选项
            marked.setOptions({
                breaks: true,  // 支持换行
                gfm: true,     // GitHub Flavored Markdown
                sanitize: false, // 允许HTML（已转义）
                highlight: function(code, lang) {
                    // 简单的代码高亮提示
                    return `<pre><code class="language-${lang}">${escapeHtml(code)}</code></pre>`;
                }
            });
            return sanitizeRenderedHtml(marked.parse(content));
        } catch (e) {
            console.error('Markdown解析失败:', e);
        }
    }

    // 降级处理：简单格式化
    let formatted = escapeHtml(content);

    // 处理换行
    formatted = formatted.replace(/\n/g, '<br>');

    // 处理四圣谏言格式
    formatted = formatted.replace(/【(曾国藩|芒格|巴菲特|Karpathy)】/g, '<strong>【$1】</strong>');

    return formatted;
}

function sanitizeRenderedHtml(html) {
    const template = document.createElement('template');
    template.innerHTML = html;

    template.content.querySelectorAll('script, iframe, object, embed, link, meta').forEach(node => node.remove());
    template.content.querySelectorAll('*').forEach(node => {
        Array.from(node.attributes).forEach(attr => {
            const name = attr.name.toLowerCase();
            const value = attr.value || '';
            if (name.startsWith('on')) {
                node.removeAttribute(attr.name);
            }
            if ((name === 'href' || name === 'src') && /^\s*javascript:/i.test(value)) {
                node.removeAttribute(attr.name);
            }
        });
    });

    return template.innerHTML;
}

/**
 * HTML转义
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * 显示加载状态
 */
function showLoading() {
    const messagesDiv = document.getElementById('messages');
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message assistant loading-message';
    loadingDiv.innerHTML = `
        <div class="message-content">
            <span class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
            </span>
        </div>
    `;
    messagesDiv.appendChild(loadingDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    return loadingDiv;
}

/**
 * 移除加载状态
 */
function removeLoading(loadingDiv) {
    if (loadingDiv && loadingDiv.parentNode) {
        loadingDiv.parentNode.removeChild(loadingDiv);
    }
}

function updateAssistantMessage(messageDiv, content, sources = null) {
    if (!messageDiv) return;
    let html = `<div class="message-content">${formatContent(content || '')}`;
    if (sources && sources.length > 0) {
        html += `<div class="message-sources">📚 来源: `;
        html += sources.slice(0, 3).map(s => `<a href="#" onclick="viewDiary(${s.id}); return false;">${s.date}</a>`).join(', ');
        if (sources.length > 3) html += ` 等${sources.length}篇`;
        html += `</div>`;
    }
    html += `</div>`;
    messageDiv.innerHTML = html;
}

async function readSseResponse(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';

        for (const rawEvent of events) {
            const lines = rawEvent.split('\n');
            const eventLine = lines.find(line => line.startsWith('event:'));
            const dataLines = lines.filter(line => line.startsWith('data:'));
            const event = eventLine ? eventLine.slice(6).trim() : 'message';
            const dataText = dataLines.map(line => line.slice(5).trimStart()).join('\n');
            if (!dataText) continue;
            try {
                onEvent(event, JSON.parse(dataText));
            } catch (error) {
                console.warn('流式事件解析失败:', error, dataText);
            }
        }
    }
}

/**
 * 设置发送按钮状态
 */
function setSendingState(sending) {
    const sendBtn = document.getElementById('sendBtn');
    const userInput = document.getElementById('userInput');

    if (sending) {
        sendBtn.classList.add('loading');
        sendBtn.disabled = true;
        userInput.disabled = true;
    } else {
        sendBtn.classList.remove('loading');
        sendBtn.disabled = false;
        userInput.disabled = false;
        userInput.focus();
    }
}

// ==================== 对话功能 ====================

/**
 * 发送消息
 * @param message 消息文本
 * @param images 图片URL数组（可选）
 */
async function sendMessage(message, images = []) {
    if (!message || !message.trim()) return;

    console.log('[app.js sendMessage] 收到参数:', { message, images });

    // 获取当前模式
    const isQueryMode = document.querySelector('.chat-container').classList.contains('query-mode');

    const append = getPublicAppendMessage();

    // 显示用户消息（传递图片用于显示）
    append('user', message, null, true, images.length > 0 ? images : null);

    // 清空输入框
    document.getElementById('userInput').value = '';
    document.getElementById('userInput').style.height = 'auto';

    // 显示加载状态
    setSendingState(true);
    const loadingDiv = showLoading();

    try {
        let endpoint, body;

        if (isQueryMode) {
            // 查询模式：使用/api/query
            endpoint = '/api/query';
            body = {
                question: message,
                images: images,
                style: window.currentStyle || 'four_sages',
                custom_style_prompt: window.customStylePrompt || ''
            };
        } else {
            // 日记模式：使用/api/chat，携带风格参数
            endpoint = '/api/chat/stream';
            body = {
                message: message,
                images: images,
                style: window.currentStyle || 'four_sages',
                custom_style_prompt: window.customStylePrompt || ''
            };
        }

        console.log('发送消息:', { endpoint, images: images });

        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(body)
        });

        // 移除加载状态
        removeLoading(loadingDiv);

        if (response.ok) {
            if (!isQueryMode && response.body) {
                const assistantDiv = append('assistant', '', null, false);
                let assistantReply = '';
                await readSseResponse(response, (event, payload) => {
                    if (event === 'delta') {
                        assistantReply += payload.text || '';
                        updateAssistantMessage(assistantDiv, assistantReply);
                        scrollMessagesToBottom();
                    } else if (event === 'done') {
                        assistantReply = payload.reply || assistantReply;
                        updateAssistantMessage(assistantDiv, assistantReply);
                    } else if (event === 'error') {
                        assistantReply = payload.error || 'AI回复生成失败，请稍后重试。';
                        updateAssistantMessage(assistantDiv, assistantReply);
                    }
                });
                setTimeout(() => reconcileConversationIfNeeded(assistantReply), 500);
            } else {
                const data = await response.json();
                const assistantReply = data.answer || data.reply || '我收到了，但这次没有生成有效回复。';
                append('assistant', assistantReply, data.sources);
                setTimeout(() => reconcileConversationIfNeeded(assistantReply), 500);
            }
        } else {
            const data = await response.json().catch(() => ({}));
            append('assistant', '抱歉，出错了：' + (data.error || '未知错误'));
        }

    } catch (error) {
        removeLoading(loadingDiv);
        append('assistant', '网络错误，请检查连接后重试。');
    } finally {
        setSendingState(false);
        scrollMessagesToBottom();
    }
}

/**
 * 判断是否为问答查询
 */
function isQuestionQuery(text) {
    const questionIndicators = [
        '什么', '怎么', '如何', '哪', '多少', '吗', '呢',
        '昨天', '今天', '最近', '上周', '本', '这',
        '关于', '记录', '日记', '统计', '趋势'
    ];
    return questionIndicators.some(kw => text.includes(kw));
}

/**
 * 保存日记
 */
async function saveDiary(content) {
    const date = new Date().toISOString().split('T')[0];

    try {
        const response = await fetch('/api/diary', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ content, date })
        });

        const data = await response.json();

        if (response.ok) {
            console.log('日记已保存:', data.diary);
            return true;
        } else {
            console.error('保存失败:', data.error);
            return false;
        }
    } catch (error) {
        console.error('保存失败:', error);
        return false;
    }
}

/**
 * 查看日记详情
 */
async function viewDiary(diaryId) {
    try {
        const response = await fetch(`/api/diary/${diaryId}`);
        const data = await response.json();

        if (response.ok) {
            const diary = data.diary;

            // 创建模态框显示
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content large">
                    <div class="modal-header">
                        <h2>${diary.date}</h2>
                        <button class="modal-close" onclick="this.closest('.modal').remove()">×</button>
                    </div>
                    <div class="modal-body">
                        <pre>${diary.content}</pre>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            modal.addEventListener('click', (e) => {
                if (e.target === modal) modal.remove();
            });
        }
    } catch (error) {
        alert('加载日记失败');
    }
}

// ==================== 自动调整文本框高度 ====================

function autoResizeTextarea(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
}

// ==================== 日报配置功能 ====================

let reportConfig = {
    enabled: true,
    push_time: '08:00',
    topics: ['今日天气与提醒', '行业动态与新闻', '个人成长建议', '健康生活提示', '今日推荐阅读'],
    custom_topics: []
};

/**
 * 从 localStorage 加载自定义话题
 */
function loadCustomTopics() {
    const saved = localStorage.getItem('customReportTopics');
    if (saved) {
        try {
            const savedTopics = JSON.parse(saved);
            if (Array.isArray(savedTopics)) {
                const existingTopics = Array.isArray(reportConfig.custom_topics) ? reportConfig.custom_topics : [];
                reportConfig.custom_topics = Array.from(new Set([...existingTopics, ...savedTopics]));
            }
        } catch (e) {
            console.error('加载自定义话题失败:', e);
        }
    }
    normalizeCustomTopics();
    renderCustomTopics();
}

/**
 * 保存自定义话题到 localStorage
 */
function saveCustomTopics() {
    localStorage.setItem('customReportTopics', JSON.stringify(reportConfig.custom_topics));
}

function normalizeCustomTopics() {
    const customTopics = Array.isArray(reportConfig.custom_topics) ? reportConfig.custom_topics : [];
    const selectedCustomTopics = (Array.isArray(reportConfig.topics) ? reportConfig.topics : [])
        .filter(topic => typeof topic === 'string' && topic.startsWith('custom:'))
        .map(topic => topic.replace(/^custom:/, '').trim())
        .filter(Boolean);

    reportConfig.custom_topics = Array.from(new Set([...customTopics, ...selectedCustomTopics]));
}

/**
 * 渲染自定义话题列表
 */
function renderCustomTopics() {
    const container = document.getElementById('customTopicList');
    if (!container) return;

    container.innerHTML = '';

    normalizeCustomTopics();

    reportConfig.custom_topics.forEach((topic, index) => {
        const item = document.createElement('div');
        item.className = 'custom-topic-item';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = `custom:${topic}`;
        checkbox.checked = reportConfig.topics.includes('custom:' + topic);

        const label = document.createElement('span');
        label.textContent = topic;

        const removeButton = document.createElement('button');
        removeButton.className = 'remove-topic';
        removeButton.dataset.index = index;
        removeButton.type = 'button';
        removeButton.textContent = '×';

        item.appendChild(checkbox);
        item.appendChild(label);
        item.appendChild(removeButton);
        container.appendChild(item);
    });

    // 绑定删除事件
    container.querySelectorAll('.remove-topic').forEach(btn => {
        btn.addEventListener('click', function() {
            const index = parseInt(this.dataset.index);
            removeCustomTopic(index);
        });
    });

    // 绑定复选框事件
    container.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            if (this.checked) {
                if (!reportConfig.topics.includes(this.value)) {
                    reportConfig.topics.push(this.value);
                }
            } else {
                reportConfig.topics = reportConfig.topics.filter(t => t !== this.value);
            }
        });
    });
}

/**
 * 添加自定义话题
 */
function addCustomTopic() {
    const input = document.getElementById('customTopicInput');
    const topic = input?.value?.trim();

    if (!topic) {
        showNotification('请输入话题名称', 'error');
        return;
    }

    if (reportConfig.custom_topics.includes(topic)) {
        showNotification('该话题已存在', 'error');
        return;
    }

    reportConfig.custom_topics.push(topic);
    const topicValue = 'custom:' + topic;
    if (!reportConfig.topics.includes(topicValue)) {
        reportConfig.topics.push(topicValue);
    }
    saveCustomTopics();
    renderCustomTopics();

    if (input) {
        input.value = '';
    }
    showNotification('话题已添加', 'success');
}

/**
 * 删除自定义话题
 */
function removeCustomTopic(index) {
    const topic = reportConfig.custom_topics[index];
    reportConfig.custom_topics.splice(index, 1);
    // 从选中列表中移除
    reportConfig.topics = reportConfig.topics.filter(t => t !== 'custom:' + topic);
    saveCustomTopics();
    renderCustomTopics();
}

/**
 * 加载日报配置
 */
async function loadReportConfig() {
    try {
        const response = await fetch('/api/report/config');
        if (response.ok) {
            const data = await response.json();
            reportConfig = data.config;
            normalizeCustomTopics();
            updateReportUI();
            renderCustomTopics();
        }
    } catch (error) {
        console.error('加载日报配置失败:', error);
    }
}

/**
 * 更新日报UI显示
 */
function updateReportUI() {
    const enabledCheckbox = document.getElementById('reportEnabled');
    const pushTimeInput = document.getElementById('reportPushTime');
    const topicCheckboxes = document.querySelectorAll('.topic-checkbox input');

    if (enabledCheckbox) enabledCheckbox.checked = reportConfig.enabled;
    if (pushTimeInput) pushTimeInput.value = reportConfig.push_time;

    topicCheckboxes.forEach(checkbox => {
        checkbox.checked = reportConfig.topics.includes(checkbox.value);
    });

    renderCustomTopics();
}

/**
 * 保存日报配置
 */
async function saveReportConfig() {
    const enabledCheckbox = document.getElementById('reportEnabled');
    const pushTimeInput = document.getElementById('reportPushTime');
    const topicCheckboxes = document.querySelectorAll('.topic-checkbox input:checked');
    const customTopicCheckboxes = document.querySelectorAll('#customTopicList input:checked');

    const topics = Array.from(topicCheckboxes).map(cb => cb.value);
    // 添加选中的自定义话题
    Array.from(customTopicCheckboxes).forEach(cb => {
        topics.push(cb.value);
    });

    const config = {
        enabled: enabledCheckbox.checked,
        push_time: pushTimeInput.value,
        topics: Array.from(new Set(topics)),
        custom_topics: Array.from(new Set(reportConfig.custom_topics))
    };

    try {
        const response = await fetch('/api/report/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (response.ok) {
            const data = await response.json();
            reportConfig = data.config;
            normalizeCustomTopics();
            saveCustomTopics();
            renderCustomTopics();
            if (data.today_report_generated) {
                showNotification('配置已保存，并已生成今日日报', 'success');
            } else if (data.today_report) {
                showNotification('配置已保存，今日日报已就绪', 'success');
            } else {
                showNotification('配置已保存', 'success');
            }
        } else {
            showNotification('保存配置失败', 'error');
        }
    } catch (error) {
        console.error('保存配置失败:', error);
        showNotification('保存配置失败', 'error');
    }
}

/**
 * 后台确保今日日报已经生成
 */
async function ensureTodayReportPrepared() {
    try {
        const response = await fetch('/api/report/today?ensure=true', { cache: 'no-store' });
        if (!response.ok) return null;
        const data = await response.json();
        if (data.generated) {
            showNotification('今日日报已在后台生成好', 'success');
        }
        return data.report || null;
    } catch (error) {
        console.warn('后台准备今日日报失败:', error);
        return null;
    }
}

/**
 * 生成日报
 */
async function generateReport(showPreview = true) {
    // 显示加载提示
    const loadingNotification = document.createElement('div');
    loadingNotification.className = 'notification notification-info';
    loadingNotification.innerHTML = '<span class="loading-dot"></span> 正在生成日报，请稍候...';
    loadingNotification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        background: #2196F3;
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 2000;
        animation: slideIn 0.3s ease;
    `;
    document.body.appendChild(loadingNotification);

    try {
        const response = await fetch('/api/report/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topics: Array.from(new Set(reportConfig.topics || [])) })
        });

        // 移除加载提示
        loadingNotification.remove();

        if (response.ok) {
            const data = await response.json();
            if (data.error) {
                showNotification(data.error, 'error');
                return null;
            }
            if (showPreview) {
                showReportPreview(data.report);
            }
            showNotification('日报生成成功', 'success');
            return data;
        } else {
            showNotification('生成日报失败', 'error');
            return null;
        }
    } catch (error) {
        loadingNotification.remove();
        console.error('生成日报失败:', error);
        showNotification('生成日报失败：网络错误', 'error');
        return null;
    }
}

/**
 * 显示报告预览
 */
function showReportPreview(content) {
    const modal = document.getElementById('reportPreviewModal');
    const previewContent = document.getElementById('reportPreviewContent');

    if (previewContent) {
        const rendered = typeof marked !== 'undefined' ? marked.parse(content) : escapeHtml(content).replace(/\n/g, '<br>');
        previewContent.innerHTML = sanitizeRenderedHtml(rendered);
    }

    if (modal) modal.style.display = '';
}

/**
 * 加载历史报告
 */
async function loadReportHistory() {
    const modal = document.getElementById('reportHistoryModal');
    const loadingDiv = document.getElementById('reportHistoryLoading');
    const listDiv = document.getElementById('reportHistoryList');
    const emptyDiv = document.getElementById('reportHistoryEmpty');

    if (!modal) return;

    modal.style.display = '';
    loadingDiv.style.display = 'block';
    listDiv.style.display = 'none';
    emptyDiv.style.display = 'none';

    try {
        const response = await fetch('/api/report/history?page=1&per_page=20');
        const data = await response.json();

        loadingDiv.style.display = 'none';

        if (response.ok && data.reports && data.reports.length > 0) {
            listDiv.style.display = 'block';

            let html = '<div class="report-history-items">';
            data.reports.forEach(report => {
                const date = new Date(report.report_date).toLocaleDateString('zh-CN', {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                    weekday: 'short'
                });
                html += `
                    <div class="report-history-item">
                        <div class="report-history-header">
                            <span class="report-history-date">${date}</span>
                            <span class="report-history-summary">${escapeHtml(report.summary || '')}</span>
                        </div>
                        <div class="report-history-actions">
                            <button class="btn-small btn-secondary" onclick="viewHistoryReport(${report.id})">查看</button>
                            <button class="btn-small btn-secondary" onclick="copyHistoryReport(${report.id})">复制</button>
                        </div>
                    </div>
                `;
            });
            html += '</div>';

            if (data.total > data.reports.length) {
                html += `<p style="text-align:center;color:var(--text-muted);margin-top:16px;">显示最近 ${data.reports.length} 条，共 ${data.total} 条报告</p>`;
            }

            listDiv.innerHTML = html;
        } else {
            emptyDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('加载历史报告失败:', error);
        loadingDiv.style.display = 'none';
        emptyDiv.style.display = 'block';
        emptyDiv.querySelector('p').textContent = '加载失败，请稍后重试';
    }
}

/**
 * 查看历史报告详情
 */
async function viewHistoryReport(reportId) {
    try {
        const response = await fetch(`/api/report/${reportId}`);
        const data = await response.json();

        if (response.ok && data.report) {
            document.getElementById('reportHistoryModal').style.display = 'none';
            showReportPreview(data.report.content);
        } else {
            showNotification('加载报告详情失败', 'error');
        }
    } catch (error) {
        console.error('加载报告详情失败:', error);
        showNotification('加载报告详情失败', 'error');
    }
}

/**
 * 复制历史报告内容
 */
async function copyHistoryReport(reportId) {
    try {
        const response = await fetch(`/api/report/${reportId}`);
        const data = await response.json();

        if (response.ok && data.report) {
            navigator.clipboard.writeText(data.report.content).then(() => {
                showNotification('已复制到剪贴板', 'success');
            });
        } else {
            showNotification('复制失败', 'error');
        }
    } catch (error) {
        console.error('复制失败:', error);
        showNotification('复制失败', 'error');
    }
}

/**
 * 显示通知
 */
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        background: ${type === 'success' ? '#4CAF50' : type === 'error' ? '#f44336' : '#2196F3'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 2000;
        animation: slideIn 0.3s ease;
    `;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = 'fadeOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 2000);
}

/**
 * 初始化日报配置对话框
 */
function initReportModal() {
    const reportBtn = document.getElementById('reportBtn');
    const reportModal = document.getElementById('reportModal');
    const closeReportModal = document.getElementById('closeReportModal');
    const saveReportConfigBtn = document.getElementById('saveReportConfig');
    const generateNowBtn = document.getElementById('generateNowBtn');
    const viewHistoryBtn = document.getElementById('viewHistoryBtn');

    const previewModal = document.getElementById('reportPreviewModal');
    const closePreviewModal = document.getElementById('closePreviewModal');
    const closePreviewBtn = document.getElementById('closePreviewBtn');
    const copyReportBtn = document.getElementById('copyReportBtn');

    const historyModal = document.getElementById('reportHistoryModal');
    const closeHistoryModal = document.getElementById('closeHistoryModal');
    const closeHistoryBtn = document.getElementById('closeHistoryBtn');

    if (!reportBtn || !reportModal) return;

    // 打开配置对话框
    reportBtn.addEventListener('click', async function() {
        await loadReportConfig();
        loadCustomTopics();
        reportModal.style.display = '';
    });

    // 关闭配置对话框
    if (closeReportModal) {
        closeReportModal.addEventListener('click', function() {
            reportModal.style.display = 'none';
        });
    }

    // 关闭预览对话框
    if (closePreviewModal) {
        closePreviewModal.addEventListener('click', function() {
            previewModal.style.display = 'none';
        });
    }
    if (closePreviewBtn) {
        closePreviewBtn.addEventListener('click', function() {
            previewModal.style.display = 'none';
        });
    }

    // 关闭历史报告对话框
    if (closeHistoryModal) {
        closeHistoryModal.addEventListener('click', function() {
            if (historyModal) historyModal.style.display = 'none';
        });
    }
    if (closeHistoryBtn) {
        closeHistoryBtn.addEventListener('click', function() {
            if (historyModal) historyModal.style.display = 'none';
        });
    }

    // 保存配置
    if (saveReportConfigBtn) {
        saveReportConfigBtn.addEventListener('click', saveReportConfig);
    }

    // 立即生成
    if (generateNowBtn) {
        generateNowBtn.addEventListener('click', async function() {
            await saveReportConfig();
            reportModal.style.display = 'none';
            await generateReport(true);
        });
    }

    // 查看历史报告
    if (viewHistoryBtn) {
        viewHistoryBtn.addEventListener('click', function() {
            reportModal.style.display = 'none';
            loadReportHistory();
        });
    }

    // 复制报告
    if (copyReportBtn) {
        copyReportBtn.addEventListener('click', function() {
            const content = document.getElementById('reportPreviewContent').innerText;
            navigator.clipboard.writeText(content).then(() => {
                showNotification('已复制到剪贴板', 'success');
            });
        });
    }

    // 添加自定义话题
    const addTopicBtn = document.getElementById('addCustomTopicBtn');
    const topicInput = document.getElementById('customTopicInput');
    if (addTopicBtn) {
        addTopicBtn.addEventListener('click', addCustomTopic);
    }
    if (topicInput) {
        topicInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                addCustomTopic();
            }
        });
    }

    // 点击对话框外部关闭
    reportModal.addEventListener('click', function(e) {
        if (e.target === reportModal) {
            reportModal.style.display = 'none';
        }
    });

    previewModal.addEventListener('click', function(e) {
        if (e.target === previewModal) {
            previewModal.style.display = 'none';
        }
    });

    if (historyModal) {
        historyModal.addEventListener('click', function(e) {
            if (e.target === historyModal) {
                historyModal.style.display = 'none';
            }
        });
    }
}

// ==================== 页面初始化 ====================

document.addEventListener('DOMContentLoaded', function() {
    const chatForm = document.getElementById('chatForm');
    const userInput = document.getElementById('userInput');

    if (!chatForm || !userInput) return; // 非对话页面

    // 草稿自动保存功能
    const DRAFT_KEY = 'diary_draft';

    // 加载保存的草稿
    function loadDraft() {
        const saved = localStorage.getItem(DRAFT_KEY);
        if (saved && userInput.value === '') {
            userInput.value = saved;
            autoResizeTextarea(userInput);
        }
    }

    // 保存草稿
    function saveDraft() {
        localStorage.setItem(DRAFT_KEY, userInput.value);
    }

    // 清除草稿
    function clearDraft() {
        localStorage.removeItem(DRAFT_KEY);
    }

    // 页面加载时恢复草稿
    loadDraft();

    // 初始化日报配置对话框
    initReportModal();
    setTimeout(ensureTodayReportPrepared, 800);

    // 表单提交
    chatForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const message = userInput.value.trim();
        if (message) {
            clearDraft(); // 发送成功后清除草稿
            // 使用window.DiaryApp.sendMessage以确保调用包装后的版本
            window.DiaryApp.sendMessage(message);
        }
    });

    // 键盘事件
    userInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    // 自动调整高度 + 保存草稿
    userInput.addEventListener('input', function() {
        autoResizeTextarea(this);
        saveDraft(); // 实时保存草稿
    });

    // 手动生成今日总结，并写回当天日记
    const todaySummaryBtn = document.getElementById('todaySummaryBtn');
    if (todaySummaryBtn) {
        todaySummaryBtn.addEventListener('click', async function() {
            const append = getPublicAppendMessage();
            const oldHtml = todaySummaryBtn.innerHTML;
            todaySummaryBtn.disabled = true;
            todaySummaryBtn.innerHTML = '<span class="btn-icon">⏳</span><span class="btn-label">总结中</span>';
            const loadingDiv = showLoading();
            try {
                const response = await fetch('/api/diary/today/summary', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        style: window.currentStyle || 'four_sages',
                        custom_style_prompt: window.customStylePrompt || ''
                    })
                });
                const data = await response.json();
                removeLoading(loadingDiv);
                if (response.ok) {
                    append('assistant', data.summary || '今天还没有足够内容可以总结。');
                } else {
                    append('assistant', '总结失败：' + (data.error || '请稍后再试'));
                }
            } catch (error) {
                removeLoading(loadingDiv);
                append('assistant', '总结失败：网络连接不稳定，请稍后再试。');
            } finally {
                todaySummaryBtn.disabled = false;
                todaySummaryBtn.innerHTML = oldHtml;
            }
        });
    }

    // 浏览历史时收起输入工具，点输入框时展开，减少移动端遮挡
    const messagesDiv = document.getElementById('messages');
    const inputContainer = document.querySelector('.input-container');
    const collapseInputBtn = document.getElementById('collapseInputBtn');
    const inputExpandBall = document.getElementById('inputExpandBall');
    let compactTimer = null;

    function collapseInputToBall() {
        if (!inputContainer) return;
        inputContainer.classList.add('collapsed-to-ball');
        inputContainer.classList.remove('compact-input');
        userInput.blur();
        scrollMessagesToBottom();
    }

    function expandInputFromBall({ focus = true } = {}) {
        if (!inputContainer) return;
        inputContainer.classList.remove('collapsed-to-ball');
        inputContainer.classList.remove('compact-input');
        requestAnimationFrame(() => {
            scrollMessagesToBottom();
            if (focus) userInput.focus();
        });
    }

    if (messagesDiv && inputContainer) {
        messagesDiv.addEventListener('scroll', () => {
            if (document.activeElement === userInput) return;
            if (inputContainer.classList.contains('collapsed-to-ball')) return;
            inputContainer.classList.add('compact-input');
            clearTimeout(compactTimer);
            compactTimer = setTimeout(() => {
                if (document.activeElement !== userInput) {
                    inputContainer.classList.add('compact-input');
                }
            }, 300);
        }, { passive: true });

        userInput.addEventListener('focus', () => {
            expandInputFromBall({ focus: false });
        });
        inputContainer.addEventListener('click', (event) => {
            if (inputContainer.classList.contains('collapsed-to-ball')) {
                event.preventDefault();
                event.stopPropagation();
                expandInputFromBall();
                return;
            }
            inputContainer.classList.remove('compact-input');
        });
        messagesDiv.addEventListener('click', (event) => {
            if (window.innerWidth > 768) return;
            if (event.target.closest('a, button, input, textarea, select')) return;
            collapseInputToBall();
        });
    }

    if (collapseInputBtn) {
        collapseInputBtn.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            collapseInputToBall();
        });
    }

    if (inputExpandBall) {
        inputExpandBall.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            expandInputFromBall();
        });
        inputExpandBall.addEventListener('touchend', (event) => {
            event.preventDefault();
            event.stopPropagation();
            expandInputFromBall();
        }, { passive: false });
    }

    // 初始化聚焦
    userInput.focus();
});

// ==================== 导出 ====================

window.DiaryApp = {
    appendMessage,
    sendMessage,
    saveDiary,
    formatContent,
    viewDiary,
    scrollMessagesToBottom
};

// 添加viewDiary到全局
window.viewDiary = viewDiary;
