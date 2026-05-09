const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync('static/js/voice-utils.js', 'utf8');
const context = { window: {} };
vm.createContext(context);
vm.runInContext(source, context);

const utils = context.window.VoiceUtils;
assert(utils, 'VoiceUtils should be exported on window');

assert.strictEqual(utils.canRequestMicrophone({ isSecureContext: true, hostname: 'example.com' }), true);
assert.strictEqual(utils.canRequestMicrophone({ isSecureContext: false, hostname: '127.0.0.1' }), true);
assert.strictEqual(utils.canRequestMicrophone({ isSecureContext: false, hostname: '192.168.1.8' }), false);

assert.strictEqual(utils.formatVoiceRate(0.8), '0.8x（偏慢）');
assert.strictEqual(utils.formatVoiceRate(1), '1.0x（自然）');
assert.strictEqual(utils.formatVoiceRate(1.2), '1.2x（偏快）');

assert.strictEqual(utils.cleanSpeechText('## 标题\n**重点** [链接](https://example.com)'), '标题，重点');
assert(utils.permissionErrorMessage({ name: 'NotAllowedError' }).includes('麦克风授权'));
assert(utils.recognitionErrorMessage('network').includes('网络不可用'));
assert(utils.recognitionErrorMessage('custom-error').includes('custom-error'));

console.log('voice-utils checks passed');
