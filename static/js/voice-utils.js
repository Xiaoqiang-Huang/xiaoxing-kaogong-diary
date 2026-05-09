window.VoiceUtils = (() => {
    function isLocalTrustHost(hostname) {
        return ['localhost', '127.0.0.1', '::1'].includes(hostname);
    }

    function canRequestMicrophone({ isSecureContext, hostname }) {
        return Boolean(isSecureContext) || isLocalTrustHost(hostname);
    }

    function formatVoiceRate(rateValue) {
        const rate = Number.parseFloat(rateValue);
        const safeRate = Number.isFinite(rate) ? rate : 1;
        const label = safeRate < 0.9 ? '偏慢' : safeRate > 1.15 ? '偏快' : '自然';
        return `${safeRate.toFixed(1)}x（${label}）`;
    }

    function cleanSpeechText(text) {
        return String(text || '')
            .replace(/#{1,6}\s/g, '')
            .replace(/\*\*/g, '')
            .replace(/\*/g, '')
            .replace(/```[\s\S]*?```/g, '')
            .replace(/`[^`]+`/g, '')
            .replace(/\[[^\]]+\]\([^)]+\)/g, '')
            .replace(/\n+/g, '，')
            .trim();
    }

    function permissionErrorMessage(error = {}) {
        if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
            return '网页没有获得麦克风授权。请允许麦克风权限；如果手机端没有弹窗，多半是当前地址不是 HTTPS。';
        }
        if (error.name === 'NotFoundError') {
            return '没有检测到可用麦克风。';
        }
        return '麦克风初始化失败：' + (error.message || error.name || '未知错误');
    }

    function recognitionErrorMessage(errorCode) {
        const messages = {
            'not-allowed': '麦克风未授权。手机端请使用 HTTPS 地址，并在浏览器权限中允许麦克风。',
            'service-not-allowed': '浏览器阻止了语音识别服务。请换用 Chrome/Edge，或改用 HTTPS 地址。',
            'network': '语音识别服务网络不可用，请检查网络后重试。',
            'no-speech': '没有识别到声音，请靠近麦克风再试一次。',
            'audio-capture': '没有检测到麦克风输入。'
        };
        return messages[errorCode] || ('语音识别失败：' + errorCode);
    }

    return {
        canRequestMicrophone,
        cleanSpeechText,
        formatVoiceRate,
        isLocalTrustHost,
        permissionErrorMessage,
        recognitionErrorMessage
    };
})();
