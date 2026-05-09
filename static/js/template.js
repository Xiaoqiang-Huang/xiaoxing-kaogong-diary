/**
 * 日记模板功能
 */

// 日记模板
const diaryTemplate = `# 四圣谏言日记

> 快速记录，2分钟完成

---

## 📅 今日记录

### 今日要事（3件）

1.
2.
3.

### 一句话总结
今天：___

### 能量状态
- 精力：___/10
- 情绪：___
- 睡眠：___h

### 待办延续
- [ ] 来自昨天的：___
- [ ] 明日要做：___

### 标签
#科研 #求职 #考公 #学习 #健康 #社交

---

**提示**：
- "今日要事"：只写结果，不写过程
- "一句话总结"：如果一年后回顾，今天最值得记住的是什么？
`;

// 显示模板
function showTemplate() {
    const userInput = document.getElementById('userInput');
    const currentContent = userInput.value.trim();

    if (currentContent && !confirm('当前内容将被替换，确定要使用模板吗？')) {
        return;
    }

    // 填充今天的日期
    const today = new Date();
    const dateStr = `${today.getFullYear()}年${today.getMonth() + 1}月${today.getDate()}日`;
    const filledTemplate = diaryTemplate.replace('今日记录', dateStr);

    userInput.value = filledTemplate;
    userInput.focus();

    // 自动调整高度
    userInput.style.height = 'auto';
    userInput.style.height = Math.min(userInput.scrollHeight, 200) + 'px';
}

// 页面加载后绑定模板按钮事件
document.addEventListener('DOMContentLoaded', function() {
    const templateBtn = document.getElementById('templateBtn');
    if (templateBtn) {
        templateBtn.addEventListener('click', showTemplate);
    }
});
