/**
 * 考公复盘系统 - 前端逻辑
 */

// 全局状态
const state = {
    currentTab: 'dashboard',
    xingceQuestions: [],
    interviewRecords: [],
    interviewStandards: null,
    currentInterviewQuestion: null,
    currentEvaluation: null,
    isRecording: false,
    isPaused: false,
    recognition: null,
    interviewVoiceRecorder: null,
    interviewVoiceStream: null,
    interviewVoiceChunks: [],
    recordingStartTime: null,
    pausedTime: 0,
    timerInterval: null,
    prepTimerInterval: null,
    recommendedTime: 150, // 建议时长（秒）
    prepTime: 60, // 思考时间（秒）
    autoRestartTimer: null,
    lastTranscript: '',
    frameworkCollapsed: true,
    wordCountTimer: null
};

// ==================== 初始化 ====================

document.addEventListener('DOMContentLoaded', function() {
    applyFeatureVisibility();
    initTabs();
    loadDashboard();
    loadInterviewStandards();
    setupLogout();
    setupTextareaStats();
});

function isKaogongFeatureEnabled(feature) {
    const cfg = window.enabledFeatures?.kaogong || {};
    if (cfg.enabled === false) return false;
    const modules = cfg.modules || {};
    return modules[feature] !== false;
}

function applyFeatureVisibility() {
    const featureTabs = ['plan', 'xingce', 'interview', 'materials'];
    featureTabs.forEach(feature => {
        const enabled = isKaogongFeatureEnabled(feature);
        document.querySelectorAll(`[data-feature-tab="${feature}"], [data-feature-panel="${feature}"]`).forEach(el => {
            el.style.display = enabled ? '' : 'none';
            el.setAttribute('aria-hidden', enabled ? 'false' : 'true');
        });
        const content = document.getElementById(feature);
        if (content) {
            content.style.display = enabled ? '' : 'none';
        }
    });

    const activeTab = document.querySelector('.tab-btn.active');
    if (activeTab && activeTab.dataset.featureTab && !isKaogongFeatureEnabled(activeTab.dataset.featureTab)) {
        switchTab('dashboard');
    }

    const firstRecentTab = Array.from(document.querySelectorAll('.recent-tab'))
        .find(tab => tab.style.display !== 'none');
    if (firstRecentTab && !document.querySelector('.recent-tab.active:not([style*="display: none"])')) {
        firstRecentTab.classList.add('active');
    }
}

// 文本框输入时更新统计
function setupTextareaStats() {
    const textarea = document.getElementById('answerText');
    if (textarea) {
        textarea.addEventListener('input', () => {
            updateTranscriptStatus(textarea.value.trim() ? 'final' : '', textarea.value.trim() ? '正在文字作答' : '等待文字输入');
            updateSpeechStats();
        });
    }
}

// ==================== 标签切换 ====================

function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            switchTab(btn.dataset.tab);
        });
    });

    // 最近记录标签切换
    const recentTabs = document.querySelectorAll('.recent-tab');
    recentTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            recentTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            loadRecentRecords(tab.dataset.type);
        });
    });
}

function switchTab(tabName) {
    const tabBtn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
    const feature = tabBtn?.dataset.featureTab;
    if (feature && !isKaogongFeatureEnabled(feature)) {
        if (typeof showToast === 'function') {
            showToast('这个功能已在设置中关闭。', 'warning');
        }
        return;
    }

    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    tabContents.forEach(content => {
        content.classList.toggle('active', content.id === tabName);
    });

    state.currentTab = tabName;

    switch(tabName) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'plan':
            loadStudyPlan();
            break;
        case 'xingce':
            loadXingceQuestions();
            break;
        case 'interview':
            loadInterviewRecords();
            break;
        case 'materials':
            loadMaterials();
            break;
    }

    document.querySelector('.kaogong-container')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function openAddQuestionFlow() {
    switchTab('xingce');
    showAddQuestion();
}

function openInterviewFlow() {
    switchTab('interview');
    showInterviewPractice();
}

function openMaterialsFlow() {
    switchTab('materials');
    showUploadMaterial();
}

// ==================== 仪表板 ====================

async function loadDashboard() {
    try {
        const res = await fetch('/api/kaogong/dashboard');
        const data = await res.json();

        if (res.ok) {
            state.xingceQuestions = data.recent_xingce || [];
            state.interviewRecords = data.recent_interview || [];
            updateDashboard(data);
        }
    } catch (err) {
        console.error('加载仪表板失败', err);
    }
}

function updateDashboard(data) {
    // 行测统计
    const xingceStats = data.xingce_statistics;
    document.getElementById('xingceTotal').textContent = xingceStats.overall.total;
    document.getElementById('xingceAccuracy').textContent = xingceStats.overall.accuracy + '%';

    // 行测分类统计
    const breakdown = document.getElementById('xingceBreakdown');
    breakdown.innerHTML = '';

    const types = [
        { key: 'verbal', name: '言语理解' },
        { key: 'quantitative', name: '数量关系' },
        { key: 'reasoning', name: '判断推理' },
        { key: 'data_analysis', name: '资料分析' },
        { key: 'general', name: '常识判断' }
    ];

    types.forEach(type => {
        const stat = xingceStats[type.key];
        if (stat && stat.total > 0) {
            const item = document.createElement('div');
            item.className = 'breakdown-item';
            item.innerHTML = `
                <span class="breakdown-name">${type.name}</span>
                <span class="breakdown-value">${stat.correct}/${stat.total} (${stat.accuracy}%)</span>
            `;
            breakdown.appendChild(item);
        }
    });

    // 面试统计
    document.getElementById('interviewTotal').textContent = data.interview_count;

    // 最近面试记录
    const recentInterview = document.getElementById('recentInterview');
    if (data.recent_interview && data.recent_interview.length > 0) {
        recentInterview.innerHTML = data.recent_interview.map(record => `
            <div class="recent-item">
                <div class="recent-item-info">
                    <span>${escapeHtml(truncateText(record.question, 30))}</span>
                    <span class="recent-item-type">${escapeHtml(formatDate(record.created_at))}</span>
                </div>
            </div>
        `).join('');
    } else {
        recentInterview.innerHTML = '<p class="empty-hint">暂无面试记录</p>';
    }

    // 资料统计
    document.getElementById('materialTotal').textContent = data.material_count;
    updateTodayPlan(data.today_plan);

    // 加载最近记录
    loadRecentRecords('xingce');
}

function updateTodayPlan(plan) {
    const focus = document.getElementById('todayPlanFocus');
    const reason = document.getElementById('todayPlanReason');
    const actions = document.getElementById('todayPlanActions');

    if (!plan) {
        focus.textContent = '暂无建议';
        reason.textContent = '';
        actions.innerHTML = '';
        return;
    }

    focus.textContent = `优先：${plan.focus_name}`;
    reason.textContent = plan.reason || '';
    actions.innerHTML = (plan.actions || []).map(action => `
        <div class="plan-action">
            <div class="plan-action-title">${escapeHtml(action.title)}</div>
            <div class="plan-action-detail">${escapeHtml(action.detail)}</div>
        </div>
    `).join('');
}

function loadRecentRecords(type) {
    const container = document.getElementById('recentRecords');
    const data = type === 'xingce' ? state.xingceQuestions : state.interviewRecords;

    if (!data || data.length === 0) {
        container.innerHTML = '<p class="empty-hint">暂无记录</p>';
        return;
    }

    container.innerHTML = data.slice(0, 5).map(item => {
        if (type === 'xingce') {
            const statusClass = item.is_correct === true ? 'correct' : item.is_correct === false ? 'wrong' : 'unknown';
            const statusText = item.is_correct === true ? '✓ 正确' : item.is_correct === false ? '✗ 错误' : '? 未判定';
            return `
                <div class="recent-item">
                    <div class="recent-item-info">
                        <span>${escapeHtml(truncateText(item.content, 40))}</span>
                        <span class="recent-item-type">${escapeHtml(formatDate(item.created_at))}</span>
                    </div>
                    <span class="recent-item-status ${statusClass}">
                        ${statusText}
                    </span>
                </div>
            `;
        } else {
            return `
                <div class="recent-item">
                    <div class="recent-item-info">
                        <span>${escapeHtml(truncateText(item.question, 40))}</span>
                        <span class="recent-item-type">${escapeHtml(formatDate(item.created_at))}</span>
                    </div>
                </div>
            `;
        }
    }).join('');
}

// ==================== 行测题目 ====================

async function loadXingceQuestions() {
    const typeFilter = document.getElementById('xingceTypeFilter')?.value || '';
    const statusFilter = document.getElementById('xingceStatusFilter')?.value || '';

    let url = '/api/kaogong/xingce/questions?';
    if (typeFilter) url += `type=${typeFilter}&`;
    if (statusFilter === 'correct') url += 'correct=true&';
    if (statusFilter === 'wrong') url += 'wrong=true&';

    try {
        const res = await fetch(url);
        const data = await res.json();

        if (res.ok) {
            state.xingceQuestions = data.questions;
            renderXingceQuestions(data.questions);
        }
    } catch (err) {
        console.error('加载题目失败', err);
    }
}

function renderXingceQuestions(questions) {
    const container = document.getElementById('xingceList');

    if (!questions || questions.length === 0) {
        container.innerHTML = renderEmptyState(
            '还没有行测题记录',
            '先记录一道今天做过的题，哪怕只写错因和用时，也能开始形成数据基线。',
            '记录第一题',
            'openAddQuestionFlow()'
        );
        return;
    }

    container.innerHTML = questions.map(q => `
        <div class="question-card">
            <div class="question-header">
                <span class="question-type">${escapeHtml(getTypeName(q.question_type))}</span>
                <div class="question-status">
                    <span class="status-icon">${q.is_correct === true ? '✓' : q.is_correct === false ? '✗' : '?'}</span>
                    <span>${q.is_correct === true ? '正确' : q.is_correct === false ? '错误' : '未答'}</span>
                </div>
            </div>
            <div class="question-content">${escapeHtml(q.content)}</div>
            ${q.options && q.options.length > 0 ? `
                <div class="question-options">
                    ${q.options.map((opt, i) => {
                        const letter = ['A', 'B', 'C', 'D'][i];
                        let className = 'question-option';
                        if (q.correct_answer === letter) className += ' correct';
                        if (q.user_answer === letter && q.user_answer !== q.correct_answer) className += ' wrong';
                        return `<div class="${className}">${letter}. ${escapeHtml(opt)}</div>`;
                    }).join('')}
                </div>
            ` : ''}
            ${q.image_url ? `<img src="${escapeHtml(q.image_url)}" alt="题目图片" style="max-width:100%;border-radius:8px;margin:8px 0;">` : ''}
            <div class="question-footer">
                <div class="question-time">
                    <span>⏱️</span>
                    <span>${q.time_spent ? formatTime(q.time_spent) : '未计时'}</span>
                </div>
                <div class="question-actions">
                    ${q.analysis ? `<button class="btn-template" onclick="showAnalysis(${q.id})">查看解析</button>` : ''}
                    <button class="btn-template danger" onclick="deleteQuestion(${q.id})">删除</button>
                </div>
            </div>
        </div>
    `).join('');
}

function showAddQuestion() {
    openModal('addQuestionModal');
}

async function submitQuestion() {
    const form = document.getElementById('addQuestionForm');
    const formData = new FormData(form);
    const questionImage = document.getElementById('questionImage')?.files?.[0];

    const data = {
        question_type: formData.get('question_type'),
        content: formData.get('content'),
        options: [],
        correct_answer: formData.get('correct_answer'),
        user_answer: formData.get('user_answer'),
        is_correct: formData.get('is_correct') === 'true' ? true : formData.get('is_correct') === 'false' ? false : null,
        time_spent: parseInt(formData.get('time_spent')) || null,
        analysis: formData.get('analysis')
    };

    // 收集选项
    ['option_a', 'option_b', 'option_c', 'option_d'].forEach(opt => {
        if (formData.get(opt)) {
            data.options.push(formData.get(opt));
        }
    });

    try {
        if (questionImage) {
            const uploadData = new FormData();
            uploadData.append('file', questionImage);
            uploadData.append('type', 'image');

            const uploadRes = await fetch('/api/kaogong/upload', {
                method: 'POST',
                body: uploadData
            });

            if (!uploadRes.ok) {
                const error = await uploadRes.json();
                throw new Error(error.error || '题目图片上传失败');
            }

            const uploadResult = await uploadRes.json();
            data.image_url = uploadResult.url;
        }

        const res = await fetch('/api/kaogong/xingce/question', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (res.ok) {
            closeModal('addQuestionModal');
            form.reset();
            loadXingceQuestions();
            loadDashboard();
            showNotification('题目添加成功', 'success');
        } else {
            const error = await res.json();
            showNotification(error.error || '添加失败', 'error');
        }
    } catch (err) {
        console.error('添加题目失败', err);
        showNotification(err.message || '添加失败', 'error');
    }
}

function showAnalysis(id) {
    const question = state.xingceQuestions.find(item => item.id === id);
    if (!question || !question.analysis) {
        showNotification('暂无解析', 'info');
        return;
    }
    alert(question.analysis);
}

async function deleteQuestion(id) {
    if (!confirm('确定要删除这道题目吗？')) return;

    try {
        const res = await fetch(`/api/kaogong/xingce/question/${id}`, {
            method: 'DELETE'
        });

        if (res.ok) {
            loadXingceQuestions();
            loadDashboard();
            showNotification('删除成功', 'success');
        }
    } catch (err) {
        console.error('删除失败', err);
    }
}

// ==================== 面试复盘 ====================

async function loadInterviewStandards() {
    try {
        const res = await fetch('/api/kaogong/interview/standards');
        const data = await res.json();

        if (res.ok) {
            state.interviewStandards = data;
            updatePracticeGuidance();
        }
    } catch (err) {
        console.error('加载面试标准失败', err);
    }
}

async function loadInterviewRecords() {
    const categoryFilter = document.getElementById('interviewCategoryFilter')?.value || '';
    let url = '/api/kaogong/interview/records?';
    if (categoryFilter) url += `category=${categoryFilter}`;

    try {
        const res = await fetch(url);
        const data = await res.json();

        if (res.ok) {
            state.interviewRecords = data.records;
            renderInterviewRecords(data.records);
        }
    } catch (err) {
        console.error('加载面试记录失败', err);
    }
}

function renderInterviewRecords(records) {
    const container = document.getElementById('interviewList');

    if (!records || records.length === 0) {
        container.innerHTML = renderEmptyState(
            '还没有面试练习',
            '建议从综合分析或自我介绍开始，先保证能在2分钟内完整表达。',
            '开始第一题',
            'openInterviewFlow()'
        );
        return;
    }

    container.innerHTML = records.map(r => `
        <div class="interview-card">
            <div class="interview-header">
                <span class="interview-category">${escapeHtml(getCategoryName(r.category))}</span>
                <span class="interview-date">${escapeHtml(formatDate(r.created_at))}</span>
            </div>
            <div class="interview-question">${escapeHtml(r.question)}</div>
            <div class="interview-answer">${escapeHtml(truncateText(r.answer_text, 100))}</div>
            ${r.audio_url ? `
                <div class="interview-audio">
                    <button class="audio-play-btn" onclick="playAudio('${escapeHtml(r.audio_url)}')">▶</button>
                    <span class="audio-duration">${formatTime(r.duration)}</span>
                </div>
            ` : ''}
            ${r.ai_evaluation && Object.keys(r.ai_evaluation).length > 0 ? `
                <div style="margin-top:12px;padding:8px;background:var(--bg);border-radius:6px;font-size:13px;">
                    <strong>AI评价：</strong>${escapeHtml(r.ai_evaluation.summary || '暂无')}
                </div>
            ` : ''}
            <div class="question-footer" style="margin-top:12px;">
                <button class="btn-template" onclick="openInterviewRecord(${r.id})">查看详情</button>
                <button class="btn-template danger" onclick="deleteInterviewRecord(${r.id})">删除</button>
            </div>
        </div>
    `).join('');
}

function openInterviewRecord(id) {
    const record = state.interviewRecords.find(item => Number(item.id) === Number(id));
    if (!record) {
        showNotification('没有找到这条复盘记录，请刷新后重试', 'error');
        return;
    }

    const modal = document.getElementById('interviewRecordModal');
    const detail = document.getElementById('interviewRecordDetail');
    const evaluation = record.ai_evaluation || {};
    const scores = evaluation.scores || {};
    const scoreHtml = Object.keys(scores).length > 0
        ? `<div class="detail-score-grid">${Object.entries(scores).map(([key, value]) => `
            <div class="detail-score-item">
                <span>${escapeHtml(key)}</span>
                <strong>${escapeHtml(value)}/10</strong>
            </div>
        `).join('')}</div>`
        : '<p class="detail-muted">暂无分项评分</p>';

    detail.innerHTML = `
        <div class="detail-section">
            <div class="detail-meta">
                <span>${escapeHtml(getCategoryName(record.category))}</span>
                <span>${escapeHtml(formatDate(record.created_at))}</span>
                <span>${record.duration ? escapeHtml(formatTime(record.duration)) : '未记录用时'}</span>
            </div>
            <h3>题目</h3>
            <p>${escapeHtml(record.question)}</p>
        </div>
        <div class="detail-section">
            <h3>我的回答</h3>
            <p>${escapeHtml(record.answer_text || '未填写').replace(/\n/g, '<br>')}</p>
        </div>
        <div class="detail-section">
            <h3>自我复盘</h3>
            <p>${escapeHtml(record.self_reflection || '未填写').replace(/\n/g, '<br>')}</p>
        </div>
        <div class="detail-section">
            <h3>AI 评价</h3>
            <div class="detail-overall">总体评分：${escapeHtml(evaluation.overall_score || 'N/A')}/10</div>
            ${scoreHtml}
            <p>${escapeHtml(evaluation.summary || '暂无总结').replace(/\n/g, '<br>')}</p>
            ${evaluation.objective_feedback ? `<h4>客观反馈</h4><p>${escapeHtml(evaluation.objective_feedback).replace(/\n/g, '<br>')}</p>` : ''}
            ${evaluation.encouragement ? `<h4>鼓励</h4><p>${escapeHtml(evaluation.encouragement).replace(/\n/g, '<br>')}</p>` : ''}
        </div>
    `;

    modal.style.display = '';
    document.body.classList.add('modal-open');
}

function closeInterviewRecordModal() {
    closeModal('interviewRecordModal');
}

function showInterviewPractice() {
    openModal('interviewPracticeModal');
    document.getElementById('interviewSetup').style.display = '';
    document.getElementById('interviewSession').style.display = 'none';
    document.getElementById('interviewResult').style.display = 'none';
    document.getElementById('saveReflectionBtn').style.display = 'none';
    document.getElementById('selfReflection').value = '';

    // 重置文字作答状态
    updateVoiceStatus('paused', '文字答题模式');
    updateTranscriptStatus('', '等待文字输入');

    // 重置进度条和计时器
    document.getElementById('timerProgressBar').style.width = '0%';
    document.getElementById('timerProgressBar').classList.remove('warning', 'danger');
    document.getElementById('answerTimer').classList.remove('warning', 'danger');

    // 清理所有定时器
    clearAllTimers();

    state.currentEvaluation = null;
    updatePracticeGuidance();
}

// 清理所有定时器
function clearAllTimers() {
    if (state.timerInterval) {
        clearInterval(state.timerInterval);
        state.timerInterval = null;
    }
    if (state.prepTimerInterval) {
        clearInterval(state.prepTimerInterval);
        state.prepTimerInterval = null;
    }
    if (state.autoRestartTimer) {
        clearTimeout(state.autoRestartTimer);
        state.autoRestartTimer = null;
    }
    if (state.wordCountTimer) {
        clearInterval(state.wordCountTimer);
        state.wordCountTimer = null;
    }
}

function closeInterviewPractice() {
    closeModal('interviewPracticeModal');
    stopRecording();

    // 清理所有状态
    clearAllTimers();
    document.removeEventListener('keydown', handleSpaceKey);

    // 重置状态变量
    state.isRecording = false;
    state.isPaused = false;
    state.recordingStartTime = null;
    state.pausedTime = 0;
}

async function startInterview() {
    const category = document.getElementById('practiceCategory').value;

    // 获取题目
    try {
        let url = '/api/kaogong/interview/questions';
        if (category !== 'random') {
            url += `?category=${category}`;
        }

        const res = await fetch(url);
        const data = await res.json();

        if (res.ok && data.questions.length > 0) {
            // 随机选择一道题
            const question = category === 'random'
                ? data.questions[Math.floor(Math.random() * data.questions.length)]
                : data.questions[Math.floor(Math.random() * data.questions.length)];

            state.currentInterviewQuestion = question;
            showInterviewQuestion(question);
        }
    } catch (err) {
        console.error('获取题目失败', err);
        showNotification('获取题目失败', 'error');
    }
}

function showInterviewQuestion(question) {
    document.getElementById('interviewSetup').style.display = 'none';
    document.getElementById('interviewSession').style.display = '';
    document.getElementById('interviewResult').style.display = 'none';
    const guidance = question.guidance || {};

    // 设置建议时长
    state.recommendedTime = question.time_limit_seconds || guidance.time_limit_seconds || 150;
    const recommendedMin = Math.floor(state.recommendedTime / 60);
    const recommendedSec = state.recommendedTime % 60;
    const recommendedTimeStr = `${recommendedMin}:${String(recommendedSec).padStart(2, '0')}`;

    // 获取答题框架
    const framework = question.answer_framework || guidance.answer_framework || [];
    const measuredElements = question.measured_elements || guidance.measured_elements || [];

    // 显示题目（在作答阶段）
    document.getElementById('interviewQuestion').innerHTML = `
        <div style="margin-bottom:8px;color:var(--text-muted);font-size:13px;">${escapeHtml(question.category_name)}</div>
        <div>${escapeHtml(question.question)}</div>
        <div class="question-guidance">
            <div><strong>测评要素：</strong>${escapeHtml(measuredElements.join('、'))}</div>
            <div><strong>建议时长：</strong>${state.recommendedTime}秒 (${recommendedTimeStr})</div>
        </div>
    `;

    // 设置答题框架提示
    const frameworkContent = document.getElementById('answerFrameworkContent');
    if (framework.length > 0) {
        frameworkContent.innerHTML = framework.map((step, index) => `
            <div class="framework-step">
                <span class="framework-step-num">${index + 1}</span>
                <span>${escapeHtml(step)}</span>
            </div>
        `).join('');
        document.getElementById('answerFrameworkCard').style.display = '';
    } else {
        document.getElementById('answerFrameworkCard').style.display = 'none';
    }

    // 设置思考阶段框架
    const prepFrameworkList = document.getElementById('prepFrameworkList');
    if (framework.length > 0) {
        prepFrameworkList.innerHTML = framework.map(step => `<li>${escapeHtml(step)}</li>`).join('');
    }

    // 更新建议时长显示
    document.getElementById('recommendedTimeDisplay').textContent = recommendedTimeStr;

    // 重置状态
    document.getElementById('answerText').value = '';
    document.getElementById('answerTimer').textContent = '00:00';
    document.getElementById('currentTimeDisplay').textContent = '0:00';
    document.getElementById('timerProgressBar').style.width = '0%';
    document.getElementById('timerProgressBar').classList.remove('warning', 'danger');
    document.getElementById('answerTimer').classList.remove('warning', 'danger');
    document.getElementById('remainingTimeAlert').style.display = 'none';
    document.getElementById('speechStats').style.display = 'none';
    updateVoiceStatus('paused', '文字答题模式');
    updateTranscriptStatus('', '等待文字输入');
    resetFlowSteps();

    // 进入思考阶段
    enterPrepPhase();
}

// 重置流程步骤
function resetFlowSteps() {
    document.getElementById('flowStepPrep').className = 'flow-step active';
    document.getElementById('flowStepAnswer').className = 'flow-step';
    document.getElementById('flowStepReview').className = 'flow-step';
}

// 进入思考阶段
function enterPrepPhase() {
    document.getElementById('prepPhase').style.display = '';
    document.getElementById('answerPhase').style.display = 'none';

    // 更新流程步骤
    document.getElementById('flowStepPrep').className = 'flow-step active';
    document.getElementById('flowStepAnswer').className = 'flow-step';

    // 设置倒计时
    let remaining = state.prepTime;
    document.getElementById('prepTimer').textContent = remaining;
    document.getElementById('prepTimer').classList.remove('urgent');

    // 清除之前的定时器
    if (state.prepTimerInterval) {
        clearInterval(state.prepTimerInterval);
    }

    // 启动倒计时
    state.prepTimerInterval = setInterval(() => {
        remaining--;
        document.getElementById('prepTimer').textContent = remaining;

        if (remaining <= 10) {
            document.getElementById('prepTimer').classList.add('urgent');
        }

        if (remaining <= 0) {
            clearInterval(state.prepTimerInterval);
            startAnswerPhase();
        }
    }, 1000);
}

// 跳过思考阶段
function skipPrepPhase() {
    if (state.prepTimerInterval) {
        clearInterval(state.prepTimerInterval);
    }
    startAnswerPhase();
}

// 开始作答阶段
function startAnswerPhase() {
    if (state.prepTimerInterval) {
        clearInterval(state.prepTimerInterval);
    }

    document.getElementById('prepPhase').style.display = 'none';
    document.getElementById('answerPhase').style.display = '';

    // 更新流程步骤
    document.getElementById('flowStepPrep').className = 'flow-step completed';
    document.getElementById('flowStepAnswer').className = 'flow-step active';

    // 重置框架卡片为折叠状态
    state.frameworkCollapsed = true;
    document.getElementById('answerFrameworkCard').classList.add('collapsed');
    startTextAnswerTimer();
}

function startTextAnswerTimer() {
    clearInterval(state.timerInterval);
    state.recordingStartTime = Date.now();
    state.timerInterval = setInterval(updateTimer, 1000);
    updateTimer();
    updateSpeechStats();
    const stats = document.getElementById('speechStats');
    if (stats) stats.style.display = 'flex';
    const textarea = document.getElementById('answerText');
    if (textarea) {
        textarea.focus();
    }
}

function updatePracticeGuidance() {
    const container = document.getElementById('interviewGuidance');
    if (!container || !state.interviewStandards) return;

    const category = document.getElementById('practiceCategory')?.value || 'random';
    const key = category === 'random' ? 'comprehensive' : category;
    const guidance = state.interviewStandards.categories?.[key];

    if (!guidance) {
        container.innerHTML = '<div class="guidance-title">测评要素</div><div class="guidance-content">暂无题型说明。</div>';
        return;
    }

    container.innerHTML = `
        <div class="guidance-title">${escapeHtml(guidance.name)} · 测评重点</div>
        <div class="guidance-content">
            <div>${escapeHtml(guidance.measured_elements.join('、'))}</div>
            <div class="guidance-muted">框架：${escapeHtml(guidance.answer_framework.join(' → '))}</div>
            <div class="guidance-muted">易失分：${escapeHtml(guidance.pitfalls.slice(0, 2).join('、'))}</div>
        </div>
    `;
}

function toggleRecording() {
    toggleInterviewVoiceRecording();
}

function togglePause() {
    showNotification('服务器语音转写暂不需要暂停；请点“停止并转写”。', 'warning');
}

function startRecording() {
    return toggleInterviewVoiceRecording();
}

function canRequestMicrophoneHere() {
    const host = window.location.hostname;
    return window.isSecureContext || host === 'localhost' || host === '127.0.0.1';
}

async function toggleInterviewVoiceRecording() {
    if (state.interviewVoiceRecorder && state.interviewVoiceRecorder.state === 'recording') {
        state.interviewVoiceRecorder.stop();
        return;
    }

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        showNotification('当前浏览器不支持录音上传，请改用最新版 Edge/Chrome。', 'error');
        return;
    }
    if (!canRequestMicrophoneHere()) {
        showNotification('手机端请使用 HTTPS 公网地址访问，普通 HTTP 地址无法授权麦克风。', 'error');
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        state.interviewVoiceStream = stream;
        state.interviewVoiceChunks = [];
        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : 'audio/webm';
        state.interviewVoiceRecorder = new MediaRecorder(stream, { mimeType });
        state.interviewVoiceRecorder.ondataavailable = event => {
            if (event.data && event.data.size > 0) {
                state.interviewVoiceChunks.push(event.data);
            }
        };
        state.interviewVoiceRecorder.onstop = uploadInterviewVoiceRecording;
        state.interviewVoiceRecorder.start();
        state.isRecording = true;
        setInterviewVoiceButtonRecording(true);
        updateVoiceStatus('listening', '正在录音，停止后交给 faster-whisper 转写');
        updateTranscriptStatus('interim', '录音中，点击停止并转写');
    } catch (err) {
        console.error('启动服务器语音转写失败', err);
        showNotification('无法访问麦克风：' + (err.message || err.name || '未知错误'), 'error');
    }
}

function setInterviewVoiceButtonRecording(recording) {
    const btn = document.getElementById('interviewVoiceBtn');
    if (!btn) return;
    btn.classList.toggle('recording', recording);
    btn.textContent = recording ? '■ 停止并转写' : '🎙️ 语音转文字';
}

async function uploadInterviewVoiceRecording() {
    const stream = state.interviewVoiceStream;
    state.interviewVoiceStream = null;
    stream?.getTracks().forEach(track => track.stop());
    setInterviewVoiceButtonRecording(false);
    state.isRecording = false;

    if (!state.interviewVoiceChunks.length) {
        updateVoiceStatus('paused', '没有录到音频');
        updateTranscriptStatus('', '没有录到音频，请重试');
        return;
    }

    const blob = new Blob(state.interviewVoiceChunks, { type: state.interviewVoiceRecorder?.mimeType || 'audio/webm' });
    const formData = new FormData();
    formData.append('audio', blob, 'interview-answer.webm');
    state.interviewVoiceChunks = [];
    state.interviewVoiceRecorder = null;
    updateVoiceStatus('listening', '正在上传并转写...');
    updateTranscriptStatus('interim', '服务器转写中...');

    try {
        const response = await fetch('/api/voice/transcribe', {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        if (!response.ok) {
            const message = data.hint || data.error || '服务器转写失败';
            updateVoiceStatus('paused', message);
            updateTranscriptStatus('', message);
            showNotification(message, 'error');
            return;
        }

        if (data.text) {
            appendAnswerTranscript(data.text);
            updateVoiceStatus('paused', '服务器转写完成');
            updateTranscriptStatus('final', '已转写: ' + data.text.slice(-24));
            updateSpeechStats();
        } else {
            updateVoiceStatus('paused', '服务器没有识别出文字');
            updateTranscriptStatus('', '没有识别出文字，请靠近麦克风再试一次');
        }
    } catch (err) {
        console.error('服务器语音转写失败', err);
        updateVoiceStatus('paused', '服务器转写请求失败');
        updateTranscriptStatus('', '服务器转写请求失败，请稍后重试');
    }
}

function appendAnswerTranscript(text) {
    const textarea = document.getElementById('answerText');
    if (!textarea) return;
    const current = textarea.value.trimEnd();
    const separator = current && !/[，。！？；：,.!?;:\n]$/.test(current) ? '，' : '';
    textarea.value = current ? `${current}${separator}${text}` : text;
    state.lastTranscript = textarea.value;
    textarea.focus();
}

function stopRecording({ stopTimer = true } = {}) {
    if (state.interviewVoiceRecorder && state.interviewVoiceRecorder.state === 'recording') {
        state.interviewVoiceRecorder.stop();
    }
    state.interviewVoiceStream?.getTracks().forEach(track => track.stop());
    state.interviewVoiceStream = null;
    setInterviewVoiceButtonRecording(false);
    clearInterval(state.timerInterval);
    if (stopTimer) state.timerInterval = null;
    state.isRecording = false;
    state.isPaused = false;
    if (state.autoRestartTimer) {
        clearTimeout(state.autoRestartTimer);
        state.autoRestartTimer = null;
    }
    document.removeEventListener('keydown', handleSpaceKey);
    updateVoiceStatus('paused', '文字答题模式');
}

// 空格键控制（只在未聚焦输入框时生效）
function handleSpaceKey(e) {
    if (e.code === 'Space' && document.activeElement.tagName !== 'TEXTAREA' && document.activeElement.tagName !== 'INPUT') {
        e.preventDefault();
        toggleRecording();
    }
}

function updateTimer() {
    if (!state.recordingStartTime) return;

    const elapsed = Math.floor((Date.now() - state.recordingStartTime) / 1000);
    const minutes = Math.floor(elapsed / 60);
    const seconds = elapsed % 60;

    const timeString = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    document.getElementById('answerTimer').textContent = timeString;
    document.getElementById('currentTimeDisplay').textContent = timeString;

    // 更新进度条
    const progressBar = document.getElementById('timerProgressBar');
    const progress = Math.min((elapsed / state.recommendedTime) * 100, 100);
    progressBar.style.width = progress + '%';

    // 时间提醒
    const timerElement = document.getElementById('answerTimer');
    const warningThreshold = state.recommendedTime * 0.8;
    const dangerThreshold = state.recommendedTime;

    if (elapsed >= dangerThreshold) {
        progressBar.classList.add('danger');
        progressBar.classList.remove('warning');
        timerElement.classList.add('danger');
        timerElement.classList.remove('warning');
    } else if (elapsed >= warningThreshold) {
        progressBar.classList.add('warning');
        progressBar.classList.remove('danger');
        timerElement.classList.add('warning');
        timerElement.classList.remove('danger');
    } else {
        progressBar.classList.remove('warning', 'danger');
        timerElement.classList.remove('warning', 'danger');
    }

    // 更新剩余时间提醒
    const remaining = state.recommendedTime - elapsed;
    const remainingAlert = document.getElementById('remainingTimeAlert');
    if (remaining <= 30 && remaining > 0) {
        remainingAlert.style.display = '';
        document.getElementById('remainingTimeText').textContent = remaining + '秒';
        if (remaining <= 10) {
            remainingAlert.classList.add('danger');
        } else {
            remainingAlert.classList.remove('danger');
        }
    } else if (remaining <= 0) {
        remainingAlert.style.display = '';
        document.getElementById('remainingTimeText').textContent = '已超时';
        remainingAlert.classList.add('danger');
    } else {
        remainingAlert.style.display = 'none';
    }

    // 更新语音统计
    updateSpeechStats();
}

// 更新语音统计
function updateSpeechStats() {
    const text = document.getElementById('answerText').value;
    const wordCount = text.replace(/\s/g, '').length;
    const elapsed = state.recordingStartTime ? (Date.now() - state.recordingStartTime) / 1000 / 60 : 0;
    const speed = elapsed > 0 ? Math.round(wordCount / elapsed) : 0;

    document.getElementById('statWordCount').textContent = wordCount;
    document.getElementById('statSpeed').textContent = speed;

    // 显示统计
    if (wordCount > 0) {
        document.getElementById('speechStats').style.display = 'flex';
    }
}

// 切换框架卡片
function toggleFrameworkCard() {
    state.frameworkCollapsed = !state.frameworkCollapsed;
    const card = document.getElementById('answerFrameworkCard');
    if (state.frameworkCollapsed) {
        card.classList.add('collapsed');
    } else {
        card.classList.remove('collapsed');
    }
}

// 切换参考答案显示
function toggleReferenceAnswer() {
    const content = document.getElementById('referenceAnswerContent');
    const btn = document.getElementById('toggleRefBtn');

    if (content.style.display === 'none') {
        content.style.display = '';
        btn.textContent = '收起';
    } else {
        content.style.display = 'none';
        btn.textContent = '展开';
    }
}

// 波形动画控制
function startWaveform() {
    const bars = document.querySelectorAll('.voice-waveform-bar');
    bars.forEach((bar, index) => {
        setTimeout(() => {
            bar.classList.add('active');
        }, index * 50);
    });
}

function stopWaveform() {
    const bars = document.querySelectorAll('.voice-waveform-bar');
    bars.forEach(bar => {
        bar.classList.remove('active');
    });
}

// 更新语音状态指示器
function updateVoiceStatus(status, text) {
    const indicator = document.getElementById('voiceStatusIndicator');
    const statusText = document.getElementById('voiceStatusText');

    indicator.className = 'voice-status-indicator ' + status;
    statusText.textContent = text;
}

// 更新转写状态
function updateTranscriptStatus(status, text) {
    const statusElement = document.getElementById('transcriptStatus');
    const statusText = document.getElementById('transcriptStatusText');

    statusElement.className = 'transcript-status ' + status;
    statusText.textContent = text;
}

async function submitAnswer() {
    if (state.isRecording) {
        showNotification('请先点击“停止并转写”，等文字出现在回答框后再提交。', 'warning');
        return;
    }

    stopRecording();

    const answer = document.getElementById('answerText').value;
    if (!answer.trim()) {
        showNotification('请输入你的回答', 'error');
        return;
    }

    // 计算实际用时
    const duration = state.recordingStartTime ? Math.floor((Date.now() - state.recordingStartTime) / 1000) : 0;

    // 显示加载状态
    document.getElementById('interviewSession').style.display = 'none';
    document.getElementById('interviewResult').style.display = '';
    document.getElementById('evaluationContent').innerHTML = '<p class="loading">AI正在评价...</p>';
    setPracticeStep(2);
    updateVoiceStatus('paused', '正在分析文字回答...');

    // 调用AI评价
    try {
        const res = await fetch('/api/kaogong/interview/evaluate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: state.currentInterviewQuestion.question,
                answer: answer,
                category: state.currentInterviewQuestion.category,
                duration: duration
            })
        });

        const data = await res.json();

        if (res.ok) {
            state.currentEvaluation = data.evaluation;
            renderEvaluation(data.evaluation);
            document.getElementById('saveReflectionBtn').style.display = '';
            updateVoiceStatus('paused', '评价完成');
        } else {
            document.getElementById('evaluationContent').innerHTML = '<p style="color:var(--danger);">评价失败，请稍后重试</p>';
            updateVoiceStatus('paused', '评价失败');
        }
    } catch (err) {
        console.error('评价失败', err);
        document.getElementById('evaluationContent').innerHTML = '<p style="color:var(--danger);">评价失败，请稍后重试</p>';
        updateVoiceStatus('paused', '网络错误');
    }
}

function renderEvaluation(evaluation) {
    let html = '';

    if (evaluation.scores) {
        html += '<div class="evaluation-scores">';
        Object.entries(evaluation.scores).forEach(([key, value]) => {
            html += `
                <div class="score-item">
                    <span class="score-name">${escapeHtml(key)}</span>
                    <span class="score-value">${escapeHtml(value)}/10</span>
                </div>
            `;
        });
        html += '</div>';
    }

    html += `<div class="evaluation-summary">`;
    html += `<div style="font-size:16px;font-weight:600;margin-bottom:8px;">总体评分：${escapeHtml(evaluation.overall_score || 'N/A')}/10</div>`;

    if (evaluation.objective_assessment) {
        html += `<div class="evaluation-section evaluation-objective">
            <h4>客观评价</h4>
            <p>${escapeHtml(evaluation.objective_assessment)}</p>
        </div>`;
    }

    if (evaluation.strengths && evaluation.strengths.length > 0) {
        html += `<div class="evaluation-section">
            <h4>✓ 优点</h4>
            <ul>${evaluation.strengths.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>
        </div>`;
    }

    if (evaluation.weaknesses && evaluation.weaknesses.length > 0) {
        html += `<div class="evaluation-section">
            <h4>△ 不足</h4>
            <ul>${evaluation.weaknesses.map(w => `<li>${escapeHtml(w)}</li>`).join('')}</ul>
        </div>`;
    }

    if (evaluation.suggestions && evaluation.suggestions.length > 0) {
        html += `<div class="evaluation-section">
            <h4>→ 改进建议</h4>
            <ul>${evaluation.suggestions.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>
        </div>`;
    }

    if (evaluation.next_drill) {
        html += `<div class="evaluation-section">
            <h4>下次训练</h4>
            <p>${escapeHtml(evaluation.next_drill)}</p>
        </div>`;
    }

    if (evaluation.encouragement) {
        html += `<div class="evaluation-section evaluation-encouragement">
            <h4>鼓励与下一步</h4>
            <p>${escapeHtml(evaluation.encouragement)}</p>
        </div>`;
    }

    if (evaluation.summary) {
        html += `<div class="evaluation-section">
            <h4>总结</h4>
            <p>${escapeHtml(evaluation.summary)}</p>
        </div>`;
    }

    html += '</div>';

    document.getElementById('evaluationContent').innerHTML = html;

    // 显示参考答案（如果有）
    if (evaluation.reference_answer) {
        const refSection = document.getElementById('referenceAnswer');
        const refContent = document.getElementById('referenceAnswerContent');
        refSection.style.display = '';
        refContent.innerHTML = `<p>${escapeHtml(evaluation.reference_answer).replace(/\n/g, '</p><p>')}</p>`;
    } else {
        document.getElementById('referenceAnswer').style.display = 'none';
    }

    // 更新流程步骤
    document.getElementById('flowStepReview').className = 'flow-step active';
}

async function saveReflection() {
    const answer = document.getElementById('answerText').value;
    const reflection = document.getElementById('selfReflection').value;

    // 计算用时（使用录音开始时间到提交时间的差值）
    let duration = 0;
    if (state.recordingStartTime) {
        // 如果还在面试结果页面，使用记录的开始时间
        duration = Math.floor((Date.now() - state.recordingStartTime) / 1000);
    }

    try {
        const res = await fetch('/api/kaogong/interview/record', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                interview_type: 'structured',
                category: state.currentInterviewQuestion.category,
                question: state.currentInterviewQuestion.question,
                answer_text: answer,
                duration: duration,
                self_reflection: reflection,
                ai_evaluation: state.currentEvaluation || {}
            })
        });

        if (res.ok) {
            showNotification('复盘保存成功', 'success');
            closeInterviewPractice();
            loadInterviewRecords();
            loadDashboard();
        } else {
            const error = await res.json();
            showNotification(error.error || '保存失败', 'error');
        }
    } catch (err) {
        console.error('保存失败', err);
        showNotification('保存失败，请稍后重试', 'error');
    }
}

function skipQuestion() {
    startInterview();
}

async function deleteInterviewRecord(id) {
    if (!confirm('确定要删除这条面试记录吗？')) return;

    try {
        const res = await fetch(`/api/kaogong/interview/record/${id}`, {
            method: 'DELETE'
        });

        if (res.ok) {
            loadInterviewRecords();
            loadDashboard();
            showNotification('删除成功', 'success');
        }
    } catch (err) {
        console.error('删除失败', err);
    }
}

// ==================== 学习资料 ====================

async function loadMaterials() {
    try {
        const res = await fetch('/api/kaogong/materials');
        const data = await res.json();

        if (res.ok) {
            renderMaterials(data.materials);
        }
    } catch (err) {
        console.error('加载资料失败', err);
    }
}

function renderMaterials(materials) {
    const container = document.getElementById('materialsList');

    if (!materials || materials.length === 0) {
        container.innerHTML = renderEmptyState(
            '还没有学习资料',
            '把面试模板、岗位公告、错题截图先放进来，后续复盘时不用到处找。',
            '上传资料',
            'openMaterialsFlow()'
        );
        return;
    }

    container.innerHTML = materials.map(m => `
        <div class="material-card">
            <div class="material-icon">${escapeHtml(getFileIcon(m.file_type))}</div>
            <div class="material-info">
                <div class="material-title">${escapeHtml(m.title)}</div>
                <div class="material-meta">${escapeHtml(getMaterialTypeName(m.material_type))} · ${escapeHtml(formatDate(m.created_at))}</div>
            </div>
        </div>
    `).join('');
}

function showUploadMaterial() {
    openModal('uploadMaterialModal');
}

async function uploadMaterial() {
    const form = document.getElementById('uploadMaterialForm');
    const formData = new FormData(form);
    const file = formData.get('file');

    if (!file || !file.name) {
        showNotification('请选择上传文件', 'error');
        return;
    }

    try {
        // 先上传文件
        const uploadData = new FormData();
        uploadData.append('file', file);
        uploadData.append('type', inferUploadType(file.name));

        const fileRes = await fetch('/api/kaogong/upload', {
            method: 'POST',
            body: uploadData
        });

        if (!fileRes.ok) {
            const error = await fileRes.json();
            throw new Error(error.error || '文件上传失败');
        }

        const fileData = await fileRes.json();

        // 保存资料记录
        const res = await fetch('/api/kaogong/material', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: formData.get('title'),
                material_type: formData.get('material_type'),
                file_url: fileData.url,
                file_type: fileData.filename.split('.').pop()
            })
        });

        if (res.ok) {
            closeModal('uploadMaterialModal');
            form.reset();
            loadMaterials();
            loadDashboard();
            showNotification('资料上传成功', 'success');
        } else {
            const error = await res.json();
            showNotification(error.error || '资料保存失败', 'error');
        }
    } catch (err) {
        console.error('上传失败', err);
        showNotification(err.message || '上传失败', 'error');
    }
}

function inferUploadType(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) return 'image';
    if (ext === 'pdf') return 'pdf';
    return 'document';
}

// ==================== 工具函数 ====================

function openModal(id) {
    const modal = document.getElementById(id);
    if (!modal) return;
    modal.style.display = '';
    document.body.classList.add('modal-open');
}

function closeModal(id) {
    const modal = document.getElementById(id);
    if (!modal) return;
    modal.style.display = 'none';
    if (!document.querySelector('.modal:not([style*="display: none"])')) {
        document.body.classList.remove('modal-open');
    }
}

function renderEmptyState(title, detail, actionText, action) {
    return `
        <div class="empty-state">
            <div class="empty-state-title">${escapeHtml(title)}</div>
            <div class="empty-state-detail">${escapeHtml(detail)}</div>
            <button class="empty-state-action" onclick="${action}">${escapeHtml(actionText)}</button>
        </div>
    `;
}

function setPracticeStep(activeIndex) {
    document.querySelectorAll('.practice-step').forEach((step, index) => {
        step.classList.toggle('active', index <= activeIndex);
    });
}

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
}

function truncateText(value, maxLength) {
    const text = value == null ? '' : String(value);
    return text.length > maxLength ? `${text.substring(0, maxLength)}...` : text;
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        background: ${type === 'success' ? '#10B981' : type === 'error' ? '#EF4444' : '#2196F3'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 2000;
    `;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.remove();
    }, 2000);
}

function formatDate(dateStr) {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now - date;

    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
    if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
    if (diff < 604800000) return Math.floor(diff / 86400000) + '天前';

    return date.toLocaleDateString('zh-CN');
}

function formatTime(seconds) {
    if (!seconds) return '0秒';
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return minutes > 0 ? `${minutes}分${secs}秒` : `${secs}秒`;
}

function getTypeName(type) {
    const names = {
        'verbal': '言语理解',
        'quantitative': '数量关系',
        'reasoning': '判断推理',
        'data_analysis': '资料分析',
        'general': '常识判断'
    };
    return names[type] || type;
}

function getCategoryName(category) {
    const names = {
        'self_intro': '自我介绍',
        'comprehensive': '综合分析',
        'emergency': '应急应变',
        'interpersonal': '人际关系',
        'organization': '组织协调',
        'vocational': '职位认知',
        'situation': '情景模拟',
        'leaderless_group': '无领导小组',
        'professional': '专业专项'
    };
    return names[category] || category;
}

function getMaterialTypeName(type) {
    const names = {
        'xingce': '行测',
        'interview': '面试',
        'general': '综合'
    };
    return names[type] || type;
}

function getFileIcon(type) {
    const icons = {
        'pdf': '📄',
        'doc': '📝',
        'docx': '📝',
        'txt': '📃'
    };
    return icons[type] || '📁';
}

function setupLogout() {
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            if (confirm('确定要退出登录吗？')) {
                await fetch('/api/logout', { method: 'POST' });
                window.location.href = '/login';
            }
        });
    }
}

// 筛选器事件监听
document.getElementById('xingceTypeFilter')?.addEventListener('change', loadXingceQuestions);
document.getElementById('xingceStatusFilter')?.addEventListener('change', loadXingceQuestions);
document.getElementById('interviewCategoryFilter')?.addEventListener('change', loadInterviewRecords);
document.getElementById('practiceCategory')?.addEventListener('change', updatePracticeGuidance);

document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
        document.querySelectorAll('.modal').forEach(modal => {
            if (modal.style.display !== 'none') {
                closeModal(modal.id);
            }
        });
    }
});

document.querySelectorAll('.modal').forEach(modal => {
    modal.addEventListener('click', event => {
        if (event.target === modal) {
            closeModal(modal.id);
        }
    });
});

// ==================== 学习计划管理 ====================

async function loadStudyPlan() {
    try {
        const res = await fetch('/api/kaogong/dashboard');
        const data = await res.json();

        if (res.ok) {
            renderCheckinCard(data.checkin, data.checkin_streak);
            renderTodayTasks(data.today_tasks);
            renderGoals(data.active_goals);
        }
    } catch (err) {
        console.error('加载学习计划失败', err);
    }
}

function renderCheckinCard(checkin, streak) {
    document.getElementById('streakDays').textContent = streak || 0;

    const checkinStatus = document.getElementById('checkinStatus');
    const checkinStats = document.getElementById('checkinStats');
    const checkinBtn = document.getElementById('checkinBtn');
    const checkinTip = document.getElementById('checkinTip');

    if (checkin) {
        checkinStatus.style.display = 'none';
        checkinStats.style.display = 'block';
        document.getElementById('todayDuration').textContent = (checkin.study_duration || 0) + ' 分钟';
        document.getElementById('todayTasks').textContent = (checkin.tasks_completed || 0) + ' 个';
        document.getElementById('todayXingce').textContent = (checkin.xingce_count || 0) + ' 题';
    } else {
        checkinStatus.style.display = 'block';
        checkinStats.style.display = 'none';
        checkinTip.textContent = streak > 0 ? `已连续打卡 ${streak} 天，继续加油！` : '今天还没有打卡哦';
        checkinBtn.textContent = streak > 0 ? '继续打卡' : '立即打卡';
    }
}

function renderTodayTasks(tasks) {
    const container = document.getElementById('todayTasksList');

    if (!tasks || tasks.length === 0) {
        container.innerHTML = '<p class="empty-hint">今天还没有任务</p>';
        return;
    }

    container.innerHTML = tasks.map(task => `
        <div class="task-item ${task.status === 'completed' ? 'completed' : ''}">
            <div class="task-checkbox ${task.status === 'completed' ? 'checked' : ''}"
                 onclick="toggleTask(${task.id}, '${task.status}')">
                ${task.status === 'completed' ? '✓' : ''}
            </div>
            <div class="task-info">
                <div class="task-title">${escapeHtml(task.title)}</div>
                <div class="task-meta">${getTaskTypeName(task.task_type)}</div>
            </div>
            ${task.target_count > 1 ? `
                <div class="task-progress">
                    <span>${task.completed_count}/${task.target_count}</span>
                </div>
            ` : ''}
        </div>
    `).join('');
}

function renderGoals(goals) {
    const container = document.getElementById('goalsList');

    if (!goals || goals.length === 0) {
        container.innerHTML = renderEmptyState(
            '还没有学习目标',
            '设定一个明确的目标，让学习更有方向。比如：行测达到70分、每天练习3道面试题。',
            '新建目标',
            'showAddGoalModal()'
        );
        return;
    }

    container.innerHTML = goals.map(goal => `
        <div class="goal-card priority-${goal.priority}">
            <div class="goal-header">
                <div>
                    <div class="goal-title">
                        ${escapeHtml(goal.title)}
                        <span class="goal-type">${getGoalTypeName(goal.goal_type)}</span>
                    </div>
                </div>
                <span class="goal-status ${goal.status}">${getGoalStatusName(goal.status)}</span>
            </div>
            ${goal.description ? `<div class="goal-description">${escapeHtml(goal.description)}</div>` : ''}
            <div class="goal-progress">
                <div class="goal-progress-bar">
                    <div class="goal-progress-fill" style="width: ${goal.progress_percent}%"></div>
                </div>
                <div class="goal-progress-text">
                    <span>${goal.current_value}/${goal.target_value} ${goal.unit || ''}</span>
                    <span>${goal.progress_percent}%</span>
                </div>
            </div>
            <div class="goal-meta">
                ${goal.days_remaining !== null ? `
                    <div class="goal-meta-item">
                        <span>📅</span>
                        <span>剩余 ${goal.days_remaining} 天</span>
                    </div>
                ` : ''}
                <div class="goal-meta-item">
                    <span>⚡</span>
                    <span>${getPriorityName(goal.priority)}</span>
                </div>
            </div>
            <div class="goal-actions">
                <button class="btn-template" onclick="editGoal(${goal.id})">编辑</button>
                <button class="btn-template" onclick="updateGoalProgress(${goal.id})">更新进度</button>
                ${goal.status !== 'completed' ? `
                    <button class="btn-template danger" onclick="deleteGoal(${goal.id})">删除</button>
                ` : ''}
            </div>
        </div>
    `).join('');
}

// 打卡相关
function showCheckinModal() {
    openModal('checkinModal');
    // 设置默认日期为今天
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('checkinDuration').value = 60;
}

async function submitCheckin() {
    const duration = parseInt(document.getElementById('checkinDuration').value) || 0;
    const tasks = parseInt(document.getElementById('checkinTasks').value) || 0;
    const xingce = parseInt(document.getElementById('checkinXingce').value) || 0;
    const interview = parseInt(document.getElementById('checkinInterview').value) || 0;
    const mood = document.querySelector('input[name="mood"]:checked')?.value;
    const summary = document.getElementById('checkinSummary').value;

    try {
        const res = await fetch('/api/kaogong/checkin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                study_duration: duration,
                tasks_completed: tasks,
                xingce_count: xingce,
                interview_count: interview,
                mood: mood,
                summary: summary
            })
        });

        const data = await res.json();

        if (res.ok) {
            showNotification(`打卡成功！已连续打卡 ${data.streak} 天`, 'success');
            closeModal('checkinModal');
            loadStudyPlan();
            loadDashboard();
        } else {
            showNotification(data.error || '打卡失败', 'error');
        }
    } catch (err) {
        console.error('打卡失败', err);
        showNotification('打卡失败', 'error');
    }
}

// 任务相关
function showAddTaskModal() {
    openModal('addTaskModal');
    // 设置默认日期为今天
    document.getElementById('taskDate').value = new Date().toISOString().split('T')[0];
}

async function submitTask() {
    const type = document.getElementById('taskType').value;
    const title = document.getElementById('taskTitle').value.trim();
    const target = parseInt(document.getElementById('taskTarget').value) || 1;
    const date = document.getElementById('taskDate').value;
    const description = document.getElementById('taskDescription').value;

    if (!title) {
        showNotification('请输入任务标题', 'error');
        return;
    }
    if (!date) {
        showNotification('请选择任务日期', 'error');
        return;
    }

    try {
        const res = await fetch('/api/kaogong/task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                task_type: type,
                title: title,
                description: description,
                target_count: target,
                task_date: date
            })
        });

        if (res.ok) {
            showNotification('任务添加成功', 'success');
            closeModal('addTaskModal');
            document.getElementById('addTaskForm').reset();
            loadStudyPlan();
        } else {
            const error = await res.json();
            showNotification(error.error || '添加失败', 'error');
        }
    } catch (err) {
        console.error('添加任务失败', err);
        showNotification('添加失败', 'error');
    }
}

async function toggleTask(taskId, currentStatus) {
    const newStatus = currentStatus === 'completed' ? 'pending' : 'completed';
    const newCount = newStatus === 'completed' ? 1 : 0;

    try {
        const res = await fetch(`/api/kaogong/task/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                status: newStatus,
                completed_count: newCount
            })
        });

        if (res.ok) {
            loadStudyPlan();
        }
    } catch (err) {
        console.error('更新任务失败', err);
    }
}

// 目标相关
function showAddGoalModal() {
    openModal('addGoalModal');
}

async function submitGoal() {
    const type = document.getElementById('goalType').value;
    const title = document.getElementById('goalTitle').value.trim();
    const description = document.getElementById('goalDescription').value;
    const target = parseInt(document.getElementById('goalTarget').value);
    const unit = document.getElementById('goalUnit').value;
    const startDate = document.getElementById('goalStartDate').value;
    const endDate = document.getElementById('goalEndDate').value;
    const priority = document.getElementById('goalPriority').value;

    if (!title) {
        showNotification('请输入目标标题', 'error');
        return;
    }

    try {
        const res = await fetch('/api/kaogong/goal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                goal_type: type,
                title: title,
                description: description,
                target_value: target,
                unit: unit,
                start_date: startDate,
                end_date: endDate,
                priority: priority
            })
        });

        if (res.ok) {
            showNotification('目标创建成功', 'success');
            closeModal('addGoalModal');
            document.getElementById('addGoalForm').reset();
            loadStudyPlan();
        } else {
            const error = await res.json();
            showNotification(error.error || '创建失败', 'error');
        }
    } catch (err) {
        console.error('创建目标失败', err);
        showNotification('创建失败', 'error');
    }
}

async function updateGoalProgress(goalId) {
    const progress = prompt('请输入当前进度：');
    if (progress === null) return;

    const value = parseInt(progress);
    if (isNaN(value)) {
        showNotification('请输入有效的数字', 'error');
        return;
    }

    try {
        const res = await fetch(`/api/kaogong/goal/${goalId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_value: value })
        });

        if (res.ok) {
            showNotification('进度更新成功', 'success');
            loadStudyPlan();
        }
    } catch (err) {
        console.error('更新进度失败', err);
    }
}

async function deleteGoal(goalId) {
    if (!confirm('确定要删除这个目标吗？')) return;

    try {
        const res = await fetch(`/api/kaogong/goal/${goalId}`, {
            method: 'DELETE'
        });

        if (res.ok) {
            showNotification('目标删除成功', 'success');
            loadStudyPlan();
        }
    } catch (err) {
        console.error('删除失败', err);
    }
}

// 辅助函数
function getTaskTypeName(type) {
    const names = {
        'xingce': '行测',
        'interview': '面试',
        'reading': '阅读',
        'practice': '练习'
    };
    return names[type] || type;
}

function getGoalTypeName(type) {
    const names = {
        'xingce': '行测',
        'interview': '面试',
        'comprehensive': '综合'
    };
    return names[type] || type;
}

function getGoalStatusName(status) {
    const names = {
        'active': '进行中',
        'completed': '已完成',
        'paused': '已暂停',
        'cancelled': '已取消'
    };
    return names[status] || status;
}

function getPriorityName(priority) {
    const names = {
        'high': '高优先级',
        'medium': '中优先级',
        'low': '低优先级'
    };
    return names[priority] || priority;
}
