/**
 * 用户设置页面逻辑
 */

document.addEventListener('DOMContentLoaded', function() {
    loadSettings();
    loadAiConfig();
    setupEventListeners();
});

let currentSettings = null;

// 加载用户设置
async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();

        if (res.ok) {
            currentSettings = data.settings;
            applySettingsToUI(currentSettings);
        }
    } catch (err) {
        console.error('加载设置失败', err);
    }
}

// 应用设置到UI
function applySettingsToUI(settings) {
    const features = settings.enabled_features || {};

    // 考公模块
    const kaogong = features.kaogong || {};
    const kaogongEnabled = document.getElementById('kaogongEnabled');
    if (kaogongEnabled) {
        kaogongEnabled.checked = kaogong.enabled !== false;
    }

    // 考公子模块
    const kaogongModules = kaogong.modules || {};
    document.querySelectorAll('.feature-toggle[data-module="kaogong"]').forEach(el => {
        const feature = el.dataset.feature;
        el.checked = kaogongModules[feature] !== false;
    });

    // 日记模块
    const diary = features.diary || {};
    const diaryEnabled = document.getElementById('diaryEnabled');
    if (diaryEnabled) {
        diaryEnabled.checked = diary.enabled !== false;
    }

    // 日记子功能
    const diaryFeatures = diary.features || {};
    document.querySelectorAll('.feature-toggle[data-module="diary"]').forEach(el => {
        const feature = el.dataset.feature;
        el.checked = diaryFeatures[feature] !== false;
    });

    // 通知设置
    const notifications = features.notifications || {};
    document.getElementById('dailyReminder').checked = notifications.daily_reminder !== false;
    document.getElementById('streakReminder').checked = notifications.streak_reminder !== false;
    document.getElementById('reminderTime').value = notifications.reminder_time || '08:00';
}

// 设置事件监听
function setupEventListeners() {
    // 主模块开关
    document.getElementById('kaogongEnabled')?.addEventListener('change', function() {
        toggleModule('kaogong', this.checked);
    });

    document.getElementById('diaryEnabled')?.addEventListener('change', function() {
        toggleModule('diary', this.checked);
    });

    // 子功能开关
    document.querySelectorAll('.feature-toggle').forEach(el => {
        el.addEventListener('change', function() {
            const module = this.dataset.module;
            const feature = this.dataset.feature;
            toggleFeature(module, feature, this.checked);
        });
    });

    // 通知设置
    document.getElementById('dailyReminder')?.addEventListener('change', function() {
        saveNotificationSettings();
    });

    document.getElementById('streakReminder')?.addEventListener('change', function() {
        saveNotificationSettings();
    });

    document.getElementById('reminderTime')?.addEventListener('change', function() {
        saveNotificationSettings();
    });

    document.getElementById('aiConfigForm')?.addEventListener('submit', function(e) {
        e.preventDefault();
        saveAiConfig();
    });
}

// 切换主模块
async function toggleModule(module, enabled) {
    if (!currentSettings) return;

    const features = currentSettings.enabled_features || {};
    if (!features[module]) {
        features[module] = {};
    }
    features[module].enabled = enabled;

    // 禁用/启用子模块
    const moduleContainer = module === 'kaogong' ? document.getElementById('kaogongModules') : document.getElementById('diaryFeatures');
    if (moduleContainer) {
        if (enabled) {
            moduleContainer.classList.remove('disabled');
        } else {
            moduleContainer.classList.add('disabled');
        }
    }

    await saveSettings();
}

// 切换子功能
async function toggleFeature(module, feature, enabled) {
    if (!currentSettings) return;

    const features = currentSettings.enabled_features || {};
    if (!features[module]) {
        features[module] = {};
    }

    if (module === 'kaogong') {
        if (!features[module].modules) {
            features[module].modules = {};
        }
        features[module].modules[feature] = enabled;
    } else if (module === 'diary') {
        if (!features[module].features) {
            features[module].features = {};
        }
        features[module].features[feature] = enabled;
    }

    await saveSettings();
}

// 保存通知设置
async function saveNotificationSettings() {
    if (!currentSettings) return;

    const features = currentSettings.enabled_features || {};
    if (!features.notifications) {
        features.notifications = {};
    }

    features.notifications.daily_reminder = document.getElementById('dailyReminder').checked;
    features.notifications.streak_reminder = document.getElementById('streakReminder').checked;
    features.notifications.reminder_time = document.getElementById('reminderTime').value;

    await saveSettings();
}

// 保存设置
async function saveSettings() {
    try {
        const res = await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                enabled_features: currentSettings.enabled_features
            })
        });

        if (res.ok) {
            showSaveIndicator();
        }
    } catch (err) {
        console.error('保存设置失败', err);
    }
}

// 显示保存成功提示
function showSaveIndicator() {
    let indicator = document.querySelector('.save-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.className = 'save-indicator';
        indicator.textContent = '✓ 设置已保存';
        document.body.appendChild(indicator);
    }

    indicator.classList.add('show');
    setTimeout(() => {
        indicator.classList.remove('show');
    }, 2000);
}

function setAiStatus(text, state = '') {
    const status = document.getElementById('aiConfigStatus');
    if (!status) return;
    status.textContent = text;
    status.className = `ai-status ${state}`.trim();
}

async function loadAiConfig() {
    const form = document.getElementById('aiConfigForm');
    if (!form) return;

    try {
        const res = await fetch('/api/admin/ai-config', { cache: 'no-store' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '读取失败');

        document.getElementById('aiBaseUrl').value = data.anthropic_base_url || '';
        document.getElementById('aiApiKey').value = '';
        document.getElementById('aiKeyHint').textContent = data.anthropic_api_key_configured
            ? `当前密钥：${data.anthropic_api_key_masked}，留空则继续使用`
            : '当前未配置 API Key';
        setAiStatus(data.ai_available ? '已连接' : '未配置', data.ai_available ? 'ready' : 'missing');
    } catch (err) {
        console.error('读取AI配置失败', err);
        setAiStatus('读取失败', 'missing');
    }
}

async function saveAiConfig() {
    const btn = document.getElementById('saveAiConfigBtn');
    const baseUrl = document.getElementById('aiBaseUrl').value.trim();
    const apiKey = document.getElementById('aiApiKey').value.trim();

    const body = { anthropic_base_url: baseUrl };
    if (apiKey) body.anthropic_api_key = apiKey;

    btn.disabled = true;
    btn.textContent = '保存中...';
    setAiStatus('热重载中', '');

    try {
        const res = await fetch('/api/admin/ai-config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '保存失败');

        document.getElementById('aiApiKey').value = '';
        document.getElementById('aiKeyHint').textContent = data.anthropic_api_key_configured
            ? `当前密钥：${data.anthropic_api_key_masked}，留空则继续使用`
            : '当前未配置 API Key';
        setAiStatus(data.ai_available ? '已连接' : '未配置', data.ai_available ? 'ready' : 'missing');
        showSaveIndicator();
    } catch (err) {
        console.error('保存AI配置失败', err);
        alert(err.message || '保存AI配置失败');
        await loadAiConfig();
    } finally {
        btn.disabled = false;
        btn.textContent = '保存并热重载';
    }
}
