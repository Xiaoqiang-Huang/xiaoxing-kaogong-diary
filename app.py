"""
日记Web系统 - Flask主应用
"""
import os
import logging
import json
import re
from datetime import datetime, timedelta
from time import time
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response, stream_with_context
from functools import wraps
from werkzeug.utils import secure_filename

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from config import Config
from models import (
    db, User, Diary, Analysis, Conversation, MemoryItem, ReportConfig, DailyReport,
    XingceQuestion, InterviewRecord, StudyMaterial, XingceStatistics,
    StudyGoal, StudyTask, StudyCheckin, UserPreferences
)
from ai_engine import FourSagesEngine, DiaryAnalyzer, init_ai_engine
from query_engine import init_query_engine
from news_fetcher import init_report_generator

# 创建Flask应用
app = Flask(__name__)
app.config.from_object(Config)

# 启用压缩（大幅提升加载速度）
try:
    from flask_compress import Compress
    Compress(app)
    logger.info("已启用gzip压缩")
except ImportError:
    logger.warning("flask-compress未安装，建议安装: pip install flask-compress")

# 初始化数据库
db.init_app(app)

# 图片上传配置
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = app.config.get('ALLOWED_IMAGE_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'webp'})
ALLOWED_DOCUMENT_EXTENSIONS = app.config.get('ALLOWED_DOCUMENT_EXTENSIONS', {'pdf', 'doc', 'docx', 'txt', 'md'})
ALLOWED_AUDIO_EXTENSIONS = app.config.get('ALLOWED_AUDIO_EXTENSIONS', {'webm', 'wav', 'mp3', 'm4a', 'ogg', 'mp4'})
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 初始化AI引擎（在Flask上下文中）
four_sages_engine = None
diary_analyzer = DiaryAnalyzer()
query_engine = None
report_generator = None
login_attempts = {}
register_attempts = {}


def current_display_name():
    """Get the current user's preferred display name from the session."""
    return session.get('display_name') or session.get('username')


def ensure_runtime_schema():
    """Apply small SQLite schema additions needed by newer app versions."""
    if db.engine.dialect.name != 'sqlite':
        return

    from sqlalchemy import text

    columns = db.session.execute(text("PRAGMA table_info(users)")).fetchall()
    column_names = {column[1] for column in columns}
    if 'display_name' not in column_names:
        db.session.execute(text("ALTER TABLE users ADD COLUMN display_name VARCHAR(80)"))
        db.session.commit()


def today_str():
    return datetime.now().strftime('%Y-%m-%d')


def get_or_create_diary(user_id, date=None):
    """Return the user's diary for a date, creating an empty one if needed."""
    date = date or today_str()
    diary = Diary.query.filter_by(user_id=user_id, date=date).first()
    if diary:
        return diary

    diary = Diary(
        user_id=user_id,
        date=date,
        content=f"# {date}\n\n> 自动汇总当日记录、AI 对话、考公练习与省察材料。\n"
    )
    db.session.add(diary)
    db.session.flush()
    return diary


def append_to_diary(user_id, title, content, date=None, source=None):
    """Append a structured section to the user's diary."""
    cleaned = (content or '').strip()
    if not cleaned:
        return None

    diary = get_or_create_diary(user_id, date)
    timestamp = datetime.now().strftime('%H:%M')
    source_line = f"\n> 来源：{source}" if source else ""
    section = f"\n\n---\n\n## {timestamp} {title}{source_line}\n\n{cleaned}\n"
    diary.content = (diary.content or '').rstrip() + section
    diary.updated_at = datetime.now()
    db.session.add(diary)
    return diary


def get_or_create_user_preferences(user_id):
    """Fetch user preferences, creating defaults when absent."""
    prefs = UserPreferences.query.filter_by(user_id=user_id).first()
    if not prefs:
        prefs = UserPreferences(user_id=user_id)
        db.session.add(prefs)
        db.session.commit()
    return prefs


def get_feature_flags(user_id):
    """Return the current user's feature visibility config."""
    return get_or_create_user_preferences(user_id).get_enabled_features()


def is_user_feature_enabled(user_id, module, feature=None):
    return get_or_create_user_preferences(user_id).is_feature_enabled(module, feature)


def normalize_memory_title(text):
    text = re.sub(r'[#*`\[\]（）()，。！？!?、:：；;「」"\'\s]+', '', text or '')
    return text[:80]


def split_memory_sentences(text):
    parts = re.split(r'[\n。！？!?；;]+', text or '')
    return [part.strip(" -\t0123456789.、") for part in parts if part.strip()]


def infer_due_date(sentence):
    today = datetime.now().date()
    if '今天' in sentence or '今晚' in sentence:
        return today.strftime('%Y-%m-%d')
    if '明天' in sentence or '明日' in sentence:
        return (today + timedelta(days=1)).strftime('%Y-%m-%d')
    if '后天' in sentence:
        return (today + timedelta(days=2)).strftime('%Y-%m-%d')
    return None


def extract_todos_from_text(text):
    """Rule-based memory extraction for clear unfinished tasks."""
    todos = []
    todo_markers = (
        '待办', '还没', '没做完', '未完成', '需要', '要去', '要把', '要做',
        '计划', '准备', '继续', '记得', '提醒我', '帮我记', '明天', '明日',
        '作业', '课堂展示', '审稿', '没写', '没完成', '- [ ]'
    )
    done_markers = ('完成了', '已完成', '做完了', '搞定了', '结束了')
    for sentence in split_memory_sentences(text):
        if len(sentence) < 4 or len(sentence) > 140:
            continue
        if any(marker in sentence for marker in done_markers):
            continue
        if not any(marker in sentence for marker in todo_markers):
            continue
        if is_memory_question(sentence):
            continue
        title = re.sub(r'^(待办|计划|准备|记得|提醒我|今天|明天|明日|后天)[：:，,、\s]*', '', sentence).strip()
        title = re.sub(r'^(还需要|需要|要去|要把|要做|继续)', '', title).strip() or sentence
        todos.append({
            'title': title[:120],
            'content': sentence,
            'due_date': infer_due_date(sentence)
        })
        if len(todos) >= 5:
            break
    return todos


def extract_history_todos_from_text(text):
    """Stricter extractor for old diaries to avoid turning analysis into todos."""
    todos = []
    markers = (
        '[ ]', '- [ ]', '待办', '待办延续', '明日要做', '明天要', '明天继续',
        '还没', '未完成', '没做完', '没有做，明天', '下一步', '继续做', '继续跑',
        '继续学习', '需要问', '需要验证', '记得', '提醒我', '帮我记',
        '作业', '课堂展示', '审稿', '没写', '没完成', '还不知道怎么',
        '还没有跑通', '没有满足环境要求', '魔改以后交差'
    )
    done_markers = ('✅', '已完成', '完成✅', '做完了', '搞定了', '结束了')
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if len(line) < 5 or len(line) > 180:
            continue
        if any(marker in line for marker in done_markers):
            continue
        if not any(marker in line for marker in markers):
            continue
        if line.startswith('#') and '待办' not in line and '下一步' not in line:
            continue
        if line.startswith(('行动：', '行动:')):
            continue
        if any(phrase in line for phrase in (
            '心理状态', '说明你', '无需多想', '熔断机制', '战略上的定力', '可能有点',
            '我的记忆里', '我想直接帮你列出来', '无法准确告诉你', '提交平台',
            '命名格式', '总成绩由', '各部分的详细要求', '研究背景', '研究动机',
            '解决方法', '效果评价', '个人启发', '所有实验均以小组',
            '提交文件', '提交文件包', '需符合', '以小组为单位', '项目与提交要求'
        )):
            continue
        title = re.sub(r'^[#>*\-\s\[\]0-9.、]+', '', line).strip()
        title = re.sub(r'^(待办延续|待办|明日要做|明天要|下一步)[：:，,、\s]*', '', title).strip()
        if title.startswith(('【系统提示', '行动：', '行动:')) or '未发现具体' in title:
            continue
        if re.match(r'^第[\d\-]+周', title):
            continue
        if is_memory_question(title):
            continue
        if any(phrase in title for phrase in ('左右睡觉', '营养均衡', '清淡饭菜')) or title == '运动':
            continue
        if not title or title in ('待办延续', '待办池') or '来自昨天的：无' in title or len(title) > 80:
            continue
        todos.append({
            'title': title[:120],
            'content': line,
            'due_date': None
        })
        if len(todos) >= 8:
            break
    return todos


def collect_memory_candidate_lines(text, source_date=None, limit=20):
    """Collect broad user-written candidate lines before adaptive filtering."""
    candidates = []
    trigger_patterns = (
        r'作业', r'课堂展示', r'课程', r'实验', r'论文', r'审稿', r'项目',
        r'还没|未做|未完成|没完成|没写|没做完|还不知道|没有跑通',
        r'继续|下一步|记得|提醒|帮我记|需要|要做|要把|要去',
        r'\[ \]'
    )
    ignore_patterns = (
        r'我的记忆里|我想直接帮你|无法准确告诉你|系统提示',
        r'提交平台|命名格式|总成绩由|各部分的详细要求',
        r'心理状态|说明你|战略上的定力|无需多想',
        r'研究背景|研究动机|解决方法|效果评价|个人启发',
        r'所有实验均以小组|优先选择|成绩评定|评分标准',
        r'提交文件|提交文件包|需符合|以小组为单位|项目与提交要求',
        r'^第[\d\-]+周'
    )
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if len(line) < 5 or len(line) > 220:
            continue
        if any(re.search(pattern, line) for pattern in ignore_patterns):
            continue
        if not any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in trigger_patterns):
            continue
        cleaned = re.sub(r'^[#>*\-\s\[\]0-9.、│├└─]+', '', line).strip()
        cleaned = re.sub(r'\*\*', '', cleaned).strip()
        if not cleaned or is_memory_question(cleaned):
            continue
        candidates.append({
            'text': cleaned[:180],
            'source_date': source_date or today_str()
        })
        if len(candidates) >= limit:
            break
    return candidates


def score_memory_candidate(text):
    """Score how likely a user-written line is an unfinished task."""
    score = 0
    high = ('未做', '还没', '未完成', '没完成', '没写', '没做完', '[ ]', '记得', '提醒', '帮我记')
    action = ('跑实验', '配置', '验证', '处理', '润色', '改论文', 'Windows环境', '迁移', '审稿', '精读', 'PPT', '课堂展示', '实验一', '实验二', '作业')
    medium = ('作业', '课堂展示', '论文', '实验', '项目', '审稿', '继续', '下一步', '需要', '还不知道', '没有跑通')
    low = ('学习', '练习', '跑步', '睡觉', '饮食')
    if any(k in text for k in high):
        score += 4
    if any(k in text for k in action):
        score += 3
    if any(k in text for k in medium):
        score += 2
    if any(k in text for k in low):
        score -= 1
    if len(text) > 90 and not any(k in text for k in high):
        score -= 2
    return score


def is_low_quality_memory_title(text):
    """Filter materials that describe requirements but are not user tasks."""
    text = text or ""
    if any(k in text for k in ('跑实验', '开始跑', '继续做', '继续跑', '验证', '处理', '润色', '迁移', '审稿')):
        return False
    if len(text) > 95 and not any(k in text for k in ('未做', '还没', '未完成', '没完成', '提醒', '记得')):
        return True
    low_quality_patterns = (
        r'命名格式',
        r'平时成绩|总成绩|成绩比例|成绩评定|评分标准',
        r'提交平台|提交文件|提交要求|文件后缀',
        r'研究背景|研究动机|解决方法|效果评价|个人启发',
        r'所有实验均以小组|以小组为单位',
        r'每次课程结束后主讲教师会发布',
        r'所查询文献应为|近年来高水平文献',
        r'^第[\d\-]+周',
        r'^\(?\d+\)?[、. ]',
    )
    if any(re.search(pattern, text) for pattern in low_quality_patterns):
        # “Paper Reading 作业”“课堂展示”本身是任务，长说明才过滤。
        if len(text) <= 28 and any(k in text for k in ('作业', '展示', '实验', '论文', '项目')):
            return False
        return True
    return False


def normalize_adaptive_memory_title(text):
    title = re.sub(r'^[#>*\-\s\[\]0-9.、│├└─]+', '', text or '').strip()
    title = re.sub(r'\*\*|`', '', title)
    title = re.sub(r'【新增】|【未做】', '', title).strip()
    title = re.sub(r'[:：]\s*$', '', title).strip()
    return title[:120]


def parse_json_array_from_ai_text(text):
    """Parse a JSON array from AI text with code fences or extra prose."""
    text = (text or "").strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.IGNORECASE | re.MULTILINE).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != '[':
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            continue
    match = re.search(r'\[[\s\S]*\]', text)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def build_user_memory_profile(user_id, max_items=80):
    """Learn a lightweight per-user memory profile from accepted/open items."""
    items = MemoryItem.query.filter_by(user_id=user_id, item_type='todo')\
        .filter(MemoryItem.status.in_(('open', 'done'))).order_by(MemoryItem.updated_at.desc()).limit(max_items).all()
    keyword_counts = {}
    category_counts = {}
    for item in items:
        title = item.title or ""
        metadata = item.get_metadata()
        category = metadata.get('category') or '待办'
        category_counts[category] = category_counts.get(category, 0) + 1
        for token in re.findall(r'[一-龥A-Za-z0-9_+\-]{2,}', title):
            if token in ('继续', '需要', '作业', '实验', '论文', '项目'):
                keyword_counts[token] = keyword_counts.get(token, 0) + 2
            elif len(token) >= 3:
                keyword_counts[token] = keyword_counts.get(token, 0) + 1
    return {
        'preferred_keywords': [
            word for word, _ in sorted(keyword_counts.items(), key=lambda kv: kv[1], reverse=True)[:18]
        ],
        'common_categories': [
            name for name, _ in sorted(category_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
        ],
        'sample_titles': [item.title for item in items[:12]]
    }


def heuristic_refine_memory_candidates(candidates, max_items=16):
    refined = []
    seen = set()
    for candidate in candidates:
        text = normalize_adaptive_memory_title(candidate.get('text', ''))
        if not text or score_memory_candidate(text) < 3:
            continue
        if is_low_quality_memory_title(text):
            continue
        if text.startswith(('我下午', '我晚上', '我今天', '我主要', '我一直')):
            continue
        if re.search(r'^(一、|二、|三、).*(成绩|要求)', text):
            continue
        key = normalize_memory_title(text)
        if not key or any(key in old or old in key for old in seen):
            continue
        seen.add(key)
        refined.append({
            'title': text,
            'content': candidate.get('text', text),
            'source_date': candidate.get('source_date') or today_str(),
            'confidence': min(0.95, 0.45 + score_memory_candidate(text) * 0.08),
            'category': '待办'
        })
        if len(refined) >= max_items:
            break
    return refined


def ai_memory_extract_enabled(user_id):
    # 记忆识别现在作为日记模式的基础能力：每个用户的对话都先交给内置 AI 判断。
    # 设置页开关只影响前端展示，不再阻断后端识别，避免不同用户漏记自然语言待办。
    return True
    try:
        return get_or_create_user_preferences(user_id).is_feature_enabled('diary', 'ai_memory_extract')
    except Exception:
        return False


def ai_refine_memory_candidates(candidates, user_id=None, max_items=16):
    """Use AI when available to adapt to the user's natural task wording."""
    if (
        not candidates
        or not user_id
        or not ai_memory_extract_enabled(user_id)
        or not four_sages_engine
        or not getattr(four_sages_engine, 'is_available', lambda: False)()
    ):
        return heuristic_refine_memory_candidates(candidates, max_items=max_items)

    payload = candidates[:80]
    user_profile = build_user_memory_profile(user_id)
    prompt = f"""你要从用户自己的历史日记片段中提取“未完成事项”。

用户定义：只要用户说过要做、需要处理、还没完成、帮我记、作业/课堂展示/项目/审稿等任务，并且没有明确说“完成了/做完了/搞定了”，就视为未完成。

请排除：
- AI 助手的建议语句、心理分析、系统提示
- 只是提问“我还有哪些没完成”的句子
- 提交平台、命名格式、成绩占比等说明性要求，除非它本身就是一个需要完成的任务
- 太泛的生活习惯，除非用户明确说要提醒

请合并重复项，保留最近、最具体的说法。返回 JSON 数组，不要解释。
字段：title、category、source_date、confidence、evidence。
最多返回 {max_items} 条。

这个用户过去被识别出的待办偏好如下，请据此适配，不要套用其他用户的模板：
{json.dumps(user_profile, ensure_ascii=False, indent=2)}

候选片段：
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""
    try:
        result = four_sages_engine.chat(prompt, user_id=user_id, style='sharp')
        text = result.get('reply', '') if isinstance(result, dict) else ''
        parsed = parse_json_array_from_ai_text(text)
        if not parsed:
            return heuristic_refine_memory_candidates(candidates, max_items=max_items)
    except Exception as exc:
        logger.warning("AI记忆候选筛选失败: %s", exc)
        return heuristic_refine_memory_candidates(candidates, max_items=max_items)

    refined = []
    seen = set()
    for raw in parsed if isinstance(parsed, list) else []:
        title = normalize_adaptive_memory_title(raw.get('title') or raw.get('evidence') or '')
        if not title or is_memory_question(title):
            continue
        if is_low_quality_memory_title(title):
            continue
        try:
            confidence = float(raw.get('confidence', 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        if confidence < 0.45:
            continue
        key = normalize_memory_title(title)
        if not key or any(key in old or old in key for old in seen):
            continue
        seen.add(key)
        refined.append({
            'title': title,
            'content': raw.get('evidence') or title,
            'source_date': raw.get('source_date') or today_str(),
            'confidence': confidence,
            'category': raw.get('category') or '待办'
        })
        if len(refined) >= max_items:
            break
    return refined or heuristic_refine_memory_candidates(candidates, max_items=max_items)


def ai_extract_todos_from_message(user_id, message, max_items=5):
    """Use built-in AI to decide whether a new user message creates memory items."""
    if (
        not message
        or not user_id
        or not ai_memory_extract_enabled(user_id)
        or not four_sages_engine
        or not getattr(four_sages_engine, 'is_available', lambda: False)()
    ):
        return None

    user_profile = build_user_memory_profile(user_id)
    prompt = f"""请判断下面这条用户新对话中，是否包含需要记住的未完成事项。

用户定义：
- 用户说“要做、需要、继续、帮我记、提醒我、作业、实验、论文、项目、审稿、还没”等，通常表示未完成事项。
- 用户只是问“我还有哪些没完成/没做”这类查询问题，不要新建待办。
- 如果用户明确说“完成了/做完了/搞定了/解决了”，不要新建待办。
- 不同用户表达习惯不同，请参考该用户自己的记忆画像。

返回 JSON 数组，不要解释。没有待办就返回 []。
字段：title、content、due_date、category、confidence。
最多返回 {max_items} 条。

用户记忆画像：
{json.dumps(user_profile, ensure_ascii=False, indent=2)}

用户新对话：
{message}
"""
    try:
        result = four_sages_engine.chat(prompt, user_id=user_id, style='sharp')
        text = result.get('reply', '') if isinstance(result, dict) else ''
        parsed = parse_json_array_from_ai_text(text)
    except Exception as exc:
        logger.warning("AI新消息记忆识别失败: %s", exc)
        return None

    todos = []
    for raw in parsed if isinstance(parsed, list) else []:
        title = normalize_adaptive_memory_title(raw.get('title') or raw.get('content') or '')
        if not title or is_memory_question(title):
            continue
        if is_low_quality_memory_title(title):
            continue
        try:
            confidence = float(raw.get('confidence', 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        if confidence < 0.45:
            continue
        todos.append({
            'title': title,
            'content': raw.get('content') or title,
            'due_date': raw.get('due_date') or infer_due_date(message),
            'category': raw.get('category') or '待办',
            'confidence': confidence,
            'extractor': 'ai_message_v1'
        })
        if len(todos) >= max_items:
            break
    return todos


def extract_user_written_blocks_from_diary(content):
    """Return user-written diary blocks, excluding AI replies in assembled daily diaries."""
    content = content or ""
    parts = re.split(r'\n---\n\n', content)
    user_blocks = []
    for part in parts:
        if '来源：日记模式输入' in part or '## 快速记录' in part or '### 待办延续' in part:
            user_blocks.append(part)
    return user_blocks or [content]


def is_memory_question(text):
    text = text or ""
    keywords = (
        '还有哪些事情没做', '还有什么没做', '哪些没做', '待办',
        '未完成', '没做完', '还没做', '提醒我', '我还有什么事',
        '接下来要做什么', '明天要做什么'
    )
    if any(keyword in text for keyword in keywords):
        return True
    return bool(re.search(r'(哪些|什么).*(没写|没完成|没做|未完成)', text))


def extract_done_keys_from_text(text):
    done_markers = ('完成了', '已完成', '做完了', '搞定了', '处理完', '解决了', '结束了')
    keys = set()
    for sentence in split_memory_sentences(text):
        if not any(marker in sentence for marker in done_markers):
            continue
        cleaned = sentence
        for marker in done_markers:
            cleaned = cleaned.replace(marker, '')
        key = normalize_memory_title(cleaned)
        if key:
            keys.add(key)
    return keys


def cancel_auto_memory_items(user_id):
    for source in ('historical_diary_scan', 'diary_chat_history'):
        MemoryItem.query.filter_by(
            user_id=user_id,
            item_type='todo',
            status='open',
            source=source
        ).update({'status': 'cancelled', 'updated_at': datetime.now()})
    db.session.flush()


def backfill_memory_from_conversations(user_id, max_messages=260, max_items=20):
    """Mine diary-mode user messages through the built-in AI judgment layer."""
    messages = Conversation.query.filter_by(user_id=user_id, role='user')\
        .order_by(Conversation.created_at.asc()).limit(max_messages).all()
    if not messages:
        return []

    existing_items = MemoryItem.query.filter_by(user_id=user_id, item_type='todo')\
        .filter(MemoryItem.source != 'diary_chat_history')\
        .filter(MemoryItem.status != 'cancelled').all()
    existing_keys = {normalize_memory_title(item.title) for item in existing_items}
    done_keys = set()
    raw_candidates = []

    for msg in messages:
        content = msg.content or ""
        done_keys.update(extract_done_keys_from_text(content))
        source_date = msg.created_at.strftime('%Y-%m-%d') if msg.created_at else today_str()
        raw_candidates.extend(collect_memory_candidate_lines(content, source_date=source_date, limit=8))
        if len(raw_candidates) >= 120:
            break

    refined_candidates = ai_refine_memory_candidates(raw_candidates, user_id=user_id, max_items=max_items)
    candidates = []
    for candidate in refined_candidates:
        key = normalize_memory_title(candidate['title'])
        if not key or key in existing_keys:
            continue
        if any(key in existing_key or existing_key in key for existing_key in existing_keys if existing_key):
            continue
        if any(key in done_key or done_key in key for done_key in done_keys):
            continue
        candidates.append({
            'title': candidate['title'],
            'content': candidate['content'],
            'due_date': candidate.get('due_date'),
            'source_date': candidate.get('source_date') or today_str(),
            'confidence': candidate.get('confidence'),
            'category': candidate.get('category')
        })
        existing_keys.add(key)

    added = []
    for candidate in candidates[:max_items]:
        item = MemoryItem(
            user_id=user_id,
            item_type='todo',
            status='open',
            title=candidate['title'],
            content=candidate['content'],
            due_date=candidate.get('due_date'),
            source='diary_chat_history',
            source_date=candidate.get('source_date') or today_str()
        )
        item.set_metadata({
            'extractor': 'conversation_ai_v1' if ai_memory_extract_enabled(user_id) else 'conversation_rule_v1',
            'confidence': candidate.get('confidence'),
            'category': candidate.get('category')
        })
        db.session.add(item)
        added.append(item)

    if added:
        db.session.flush()
    return added


def backfill_memory_from_history(user_id, max_diaries=180, max_items=20, refresh=False):
    """Mine old diary files as fallback. Conversation user messages are the primary source."""
    if refresh:
        cancel_auto_memory_items(user_id)

    existing_query = MemoryItem.query.filter_by(
        user_id=user_id,
        item_type='todo'
    ).filter(MemoryItem.status != 'cancelled')
    if refresh:
        existing_query = existing_query.filter(MemoryItem.source != 'historical_diary_scan')
    existing_items = existing_query.all()
    existing_keys = {normalize_memory_title(item.title) for item in existing_items}

    diaries = Diary.query.filter_by(user_id=user_id)\
        .order_by(Diary.date.desc()).limit(max_diaries).all()
    if not diaries:
        return []

    done_keys = set()
    for diary in diaries:
        for block in extract_user_written_blocks_from_diary(diary.content or ""):
            done_keys.update(extract_done_keys_from_text(block))

    raw_candidates = []
    for diary in diaries:
        for content in extract_user_written_blocks_from_diary(diary.content or ""):
            raw_candidates.extend(collect_memory_candidate_lines(content, source_date=diary.date, limit=12))
        if len(raw_candidates) >= 120:
            break

    refined_candidates = ai_refine_memory_candidates(raw_candidates, user_id=user_id, max_items=max_items)
    candidates = []
    for candidate in refined_candidates:
        key = normalize_memory_title(candidate['title'])
        if not key or key in existing_keys:
            continue
        if any(key in existing_key or existing_key in key for existing_key in existing_keys if existing_key):
            continue
        if any(key in done_key or done_key in key for done_key in done_keys):
            continue
        candidates.append(candidate)
        existing_keys.add(key)

    added = []
    for candidate in candidates:
        item = MemoryItem(
            user_id=user_id,
            item_type='todo',
            status='open',
            title=candidate['title'],
            content=candidate['content'],
            due_date=candidate.get('due_date'),
            source='historical_diary_scan',
            source_date=candidate.get('source_date') or today_str()
        )
        item.set_metadata({
            'extractor': 'adaptive_history_v1',
            'confidence': candidate.get('confidence'),
            'category': candidate.get('category')
        })
        db.session.add(item)
        added.append(item)

    if added:
        db.session.flush()
    return added


def ensure_memory_from_history(user_id, force=False):
    open_count = MemoryItem.query.filter_by(user_id=user_id, item_type='todo', status='open').count()
    if force or open_count < 3:
        if force:
            cancel_auto_memory_items(user_id)
        added = []
        added.extend(backfill_memory_from_conversations(user_id))
        added.extend(backfill_memory_from_history(user_id, refresh=False))
        return added
    return []


def close_done_memory_items(user_id, text):
    done_markers = ('完成了', '已完成', '做完了', '搞定了', '处理完', '解决了')
    if not any(marker in (text or '') for marker in done_markers):
        return []

    open_items = MemoryItem.query.filter_by(
        user_id=user_id,
        item_type='todo',
        status='open'
    ).order_by(MemoryItem.updated_at.desc()).limit(30).all()
    closed = []
    normalized_text = normalize_memory_title(text)
    for item in open_items:
        key = normalize_memory_title(item.title)
        if key and (key in normalized_text or normalized_text in key):
            item.status = 'done'
            item.updated_at = datetime.now()
            closed.append(item)
    return closed


def sync_memory_from_message(user_id, message):
    """Update long-term memory from a diary-mode message."""
    closed = close_done_memory_items(user_id, message)
    added = []
    existing_open = MemoryItem.query.filter_by(
        user_id=user_id,
        item_type='todo',
        status='open'
    ).all()
    existing_keys = {normalize_memory_title(item.title) for item in existing_open}

    ai_todos = ai_extract_todos_from_message(user_id, message)
    todos = ai_todos if ai_todos is not None else extract_todos_from_text(message)

    for todo in todos:
        key = normalize_memory_title(todo['title'])
        if not key or key in existing_keys:
            continue
        item = MemoryItem(
            user_id=user_id,
            item_type='todo',
            status='open',
            title=todo['title'],
            content=todo['content'],
            due_date=todo.get('due_date'),
            source='diary_chat',
            source_date=today_str()
        )
        item.set_metadata({
            'extractor': todo.get('extractor') or ('ai_message_v1' if ai_todos is not None else 'rule_v1'),
            'confidence': todo.get('confidence'),
            'category': todo.get('category') or '待办'
        })
        db.session.add(item)
        added.append(item)
        existing_keys.add(key)

    if added or closed:
        db.session.flush()
    return {'added': added, 'closed': closed}


def get_open_memory_items(user_id, limit=6):
    return MemoryItem.query.filter_by(
        user_id=user_id,
        item_type='todo',
        status='open'
    ).order_by(
        MemoryItem.due_date.is_(None),
        MemoryItem.due_date.asc(),
        MemoryItem.source_date.desc(),
        MemoryItem.updated_at.desc()
    ).limit(limit).all()


def format_memory_context(user_id, limit=6):
    items = get_open_memory_items(user_id, limit=limit)
    if not items:
        return ""
    lines = ["【长期记忆：未完成事项】"]
    for item in items:
        due = f"（{item.due_date}）" if item.due_date else ""
        lines.append(f"- {item.title}{due}")
    return "\n".join(lines)


def should_show_memory_reminder(message, changes):
    reminder_keywords = ('提醒', '待办', '还没', '没做完', '今天', '明天', '计划', '接下来', '怎么办')
    return bool(changes.get('added') or changes.get('closed') or any(k in message for k in reminder_keywords))


def build_memory_reply_prefix(user_id, changes):
    open_items = get_open_memory_items(user_id, limit=5)
    lines = []
    if changes.get('added'):
        lines.append(f"已记住 {len(changes['added'])} 个未完成事项。")
    if changes.get('closed'):
        lines.append(f"已标记完成 {len(changes['closed'])} 个事项。")
    if open_items:
        lines.append("当前未完成事项：")
        lines.extend([f"- {item.title}{'（' + item.due_date + '）' if item.due_date else ''}" for item in open_items])
    return "\n".join(lines).strip()


def format_open_memory_answer(user_id, history_added=None):
    items = get_open_memory_items(user_id, limit=12)
    if not items:
        return "我刚才已经回头扫描了最近的历史日记，但没有提取到明确的未完成事项。以后你写“明天要……”“还没做完……”“待办：……”这类句子，我会自动记住。"

    lines = []
    if history_added:
        lines.append(f"我刚从历史日记里回捞并补记了 {len(history_added)} 个可能的未完成事项。")
    lines.append("你当前可能还没做完的事情：")
    for idx, item in enumerate(items, start=1):
        source = f"（来自 {item.source_date}）" if item.source_date else ""
        due = f"；目标日期 {item.due_date}" if item.due_date else ""
        lines.append(f"{idx}. {item.title}{source}{due}")
    lines.append("\n如果其中有已经完成的，直接回复“完成了 + 事项名”，我会把它划掉。")
    return "\n".join(lines)


def format_interview_evaluation_for_diary(evaluation):
    if not evaluation:
        return ""
    if isinstance(evaluation, str):
        return evaluation

    lines = []
    overall = evaluation.get('overall_score') or evaluation.get('score')
    if overall:
        lines.append(f"- 总体评分：{overall}/10")
    if evaluation.get('objective_assessment'):
        lines.append(f"- 客观评价：{evaluation['objective_assessment']}")
    if evaluation.get('encouragement'):
        lines.append(f"- 鼓励与下一步：{evaluation['encouragement']}")
    if evaluation.get('next_drill'):
        lines.append(f"- 下次训练：{evaluation['next_drill']}")
    if evaluation.get('scores'):
        score_text = "；".join([f"{k} {v}/10" for k, v in evaluation['scores'].items()])
        lines.append(f"- 维度评分：{score_text}")
    if not lines:
        lines.append("```json\n" + json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n```")
    return "\n".join(lines)


def build_interview_trend_context(user_id, limit=12):
    records = InterviewRecord.query.filter_by(user_id=user_id)\
        .order_by(InterviewRecord.created_at.desc()).limit(limit).all()
    if not records:
        return "暂无面试评价记录。"

    scores = []
    weaknesses = []
    strengths = []
    lines = []
    for record in records:
        evaluation = record.get_ai_evaluation()
        score = evaluation.get('overall_score') or evaluation.get('score')
        try:
            scores.append(float(score))
        except (TypeError, ValueError):
            pass
        strengths.extend(evaluation.get('strengths') or [])
        weaknesses.extend(evaluation.get('weaknesses') or [])
        summary = evaluation.get('objective_assessment') or evaluation.get('summary') or ''
        lines.append(f"- {record.created_at.strftime('%Y-%m-%d')} {record.category}: {score or '未评分'}分，{summary[:80]}")

    trend = ""
    if len(scores) >= 2:
        delta = scores[0] - scores[-1]
        direction = "上升" if delta > 0.3 else "下降" if delta < -0.3 else "基本稳定"
        trend = f"最近{len(scores)}次平均分 {sum(scores) / len(scores):.1f}/10，较早期趋势：{direction}。"
    elif scores:
        trend = f"最近一次评分 {scores[0]:.1f}/10。"

    common_weaknesses = "；".join(weaknesses[:5]) if weaknesses else "暂无明显高频短板。"
    common_strengths = "；".join(strengths[:5]) if strengths else "暂无明确优势标签。"
    return f"{trend}\n常见优势：{common_strengths}\n常见短板：{common_weaknesses}\n最近记录：\n" + "\n".join(lines[:8])


def generate_today_summary_text(user_id, style='four_sages', custom_style_prompt=None):
    diary = Diary.query.filter_by(user_id=user_id, date=today_str()).first()
    if not diary:
        return "今天还没有记录。先写下一个事实、一个感受、一个下一步，晚上再总结会更扎实。"

    interview_context = build_interview_trend_context(user_id, limit=10)
    prompt = f"""请把下面的当天日记、AI对话和考公练习整理成一份个人战略参谋式总结。

要求：
1. 先客观复盘：今天发生了什么、完成了什么、卡在哪里。
2. 再做省察：动机、情绪、选择、能力圈、长期复利。
3. 面试评价要单独吸收，指出趋势和下一次训练重点。
4. 风格参考四圣谏言、毛泽东思想的实事求是、长期主义、工程现实主义；语气可以温柔一点，但不要空夸。
5. 输出 Markdown，控制在 800 字以内。

当天日记：
{diary.content[-6000:]}

面试评价趋势：
{interview_context}
"""
    try:
        result = four_sages_engine.chat(
            prompt,
            user_id=user_id,
            style=style,
            custom_style_prompt=custom_style_prompt
        )
        return result.get('reply') or "总结生成失败，请稍后再试。"
    except Exception as exc:
        logger.exception("生成当天总结失败")
        return f"## 今日简要总结\n\n今天累计记录较多，但 AI 总结暂时失败：{exc.__class__.__name__}。建议先手动标记：完成事项、卡点、明日第一步。"

def init_ai_engine():
    """初始化AI引擎"""
    global four_sages_engine, query_engine, report_generator
    four_sages_engine = FourSagesEngine(
        api_key=app.config.get('ANTHROPIC_API_KEY', ''),
        base_url=app.config.get('ANTHROPIC_BASE_URL', '')
    )
    # 注入数据库模型，让AI能访问用户数据
    from ai_engine import init_ai_engine as _init_ai
    _init_ai(db, User)
    # 初始化问答引擎
    query_engine = init_query_engine(db, four_sages_engine)
    # 初始化日报生成器
    report_generator = init_report_generator(db, four_sages_engine)


def mask_secret(value):
    value = (value or '').strip()
    if not value:
        return ''
    if len(value) <= 8:
        return '*' * len(value)
    return f"{value[:4]}...{value[-4:]}"


def quote_env_value(value):
    value = '' if value is None else str(value)
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def update_dotenv_values(updates):
    """Persist runtime AI config without disturbing unrelated .env keys."""
    env_path = os.path.join(app.root_path, '.env')
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()

    remaining = dict(updates)
    output = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in line:
            output.append(line)
            continue
        key = line.split('=', 1)[0].strip()
        if key in remaining:
            output.append(f"{key}={quote_env_value(remaining.pop(key))}")
        else:
            output.append(line)

    for key, value in remaining.items():
        output.append(f"{key}={quote_env_value(value)}")

    with open(env_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(output).rstrip() + '\n')


def apply_ai_runtime_config(values):
    """Apply AI config immediately and persist it for the next restart."""
    updates = {}
    if 'ANTHROPIC_BASE_URL' in values:
        base_url = (values.get('ANTHROPIC_BASE_URL') or '').strip().rstrip('/')
        updates['ANTHROPIC_BASE_URL'] = base_url
        os.environ['ANTHROPIC_BASE_URL'] = base_url
        app.config['ANTHROPIC_BASE_URL'] = base_url
    if 'ANTHROPIC_API_KEY' in values:
        api_key = (values.get('ANTHROPIC_API_KEY') or '').strip()
        updates['ANTHROPIC_API_KEY'] = api_key
        os.environ['ANTHROPIC_API_KEY'] = api_key
        app.config['ANTHROPIC_API_KEY'] = api_key

    if updates:
        update_dotenv_values(updates)
        init_ai_engine()

    return updates

# 确保数据目录存在
os.makedirs(app.config.get('DATA_PATH', 'data'), exist_ok=True)
# 确保日记MD目录存在
os.makedirs(app.config['DIARY_MD_PATH'], exist_ok=True)


@app.after_request
def add_security_headers(response):
    """添加基础安全响应头和缓存优化。"""
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), geolocation=(), payment=()')

    # 静态资源缓存优化
    request_path = request.path
    if request_path.startswith('/static/'):
        # CSS/JS 文件长期缓存
        if request_path.endswith('.css') or request_path.endswith('.js'):
            response.cache_control.max_age = 86400 * 7  # 7天
            response.headers.add('Vary', 'Accept-Encoding')
        # 图片文件长期缓存
        elif request_path.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico')):
            response.cache_control.max_age = 86400 * 30  # 30天
            response.headers.add('Vary', 'Accept-Encoding')
        else:
            response.cache_control.max_age = 3600  # 1小时
    else:
        # HTML页面不缓存
        response.cache_control.no_cache = True
        response.cache_control.no_store = True
        response.headers.add('Vary', 'Accept-Encoding')

    return response


# ==================== 装饰器 ====================

def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': '请先登录'}), 401
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """管理员验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': '请先登录'}), 401

        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            return jsonify({'error': '需要管理员权限'}), 403

        return f(*args, **kwargs)
    return decorated_function


# ==================== 路由：页面 ====================

@app.route('/')
def index():
    """首页 - 对话界面"""
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('index.html', username=current_display_name(), features=get_feature_flags(session['user_id']))


@app.route('/admin')
def admin_page():
    """管理员页面"""
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    # 检查是否是管理员
    user = User.query.get(session['user_id'])
    if not user or not user.is_admin:
        return '需要管理员权限', 403

    return render_template('admin.html', username=current_display_name())


@app.route('/login')
def login_page():
    """登录页面"""
    return render_template('login.html')


@app.route('/register')
def register_page():
    """注册页面"""
    return render_template('register.html')


@app.route('/history')
def history_page():
    """历史记录页面"""
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('history.html', username=current_display_name(), features=get_feature_flags(session['user_id']))


@app.route('/api/health')
def health_check():
    """系统健康检查，不返回任何密钥或用户数据。"""
    from sqlalchemy import text

    database_status = 'ok'
    try:
        db.session.execute(text('SELECT 1'))
    except Exception as exc:
        logger.exception("数据库健康检查失败")
        database_status = f'error: {exc.__class__.__name__}'

    status = 'ok' if database_status == 'ok' else 'degraded'
    return jsonify({
        'status': status,
        'database': database_status,
        'ai_configured': bool(app.config.get('ANTHROPIC_API_KEY')),
        'environment': app.config.get('APP_ENV', 'development'),
        'timestamp': datetime.now().isoformat()
    }), 200 if status == 'ok' else 503


# ==================== 路由：API - 认证 ====================

@app.route('/api/register', methods=['POST'])
def register():
    """用户注册"""
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    display_name = data.get('display_name', '').strip()
    password = data.get('password', '')

    if not app.config.get('ALLOW_PUBLIC_REGISTRATION', True):
        invite_code = app.config.get('REGISTRATION_INVITE_CODE', '')
        if not invite_code or data.get('invite_code', '').strip() != invite_code:
            return jsonify({'error': '当前公网访问模式已关闭公开注册，请使用已有账号登录'}), 403

    limiter_key = f"register:{request.remote_addr or 'unknown'}"
    now = time()
    window = app.config.get('REGISTER_RATE_LIMIT_SECONDS', 600)
    max_attempts = app.config.get('REGISTER_MAX_ATTEMPTS', 6)
    attempts = [ts for ts in register_attempts.get(limiter_key, []) if now - ts < window]
    register_attempts[limiter_key] = attempts
    if len(attempts) >= max_attempts:
        return jsonify({'error': '注册尝试过多，请稍后再试'}), 429
    attempts.append(now)
    register_attempts[limiter_key] = attempts

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400

    if len(username) < 3:
        return jsonify({'error': '用户名至少3个字符'}), 400

    if len(password) < 6:
        return jsonify({'error': '密码至少6个字符'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': '用户名已存在'}), 400

    user = User(username=username, display_name=display_name or username)
    user.set_password(password)

    db.session.add(user)
    db.session.commit()

    session['user_id'] = user.id
    session['username'] = user.username
    session['display_name'] = user.get_display_name()

    return jsonify({'message': '注册成功', 'user': user.to_dict()})


@app.route('/api/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400

    limiter_key = f"{request.remote_addr or 'unknown'}:{username}"
    now = time()
    window = app.config.get('LOGIN_RATE_LIMIT_SECONDS', 300)
    max_attempts = app.config.get('LOGIN_MAX_ATTEMPTS', 8)

    attempts = [ts for ts in login_attempts.get(limiter_key, []) if now - ts < window]
    login_attempts[limiter_key] = attempts
    if len(attempts) >= max_attempts:
        return jsonify({'error': '登录尝试过多，请稍后再试'}), 429

    user = User.query.filter_by(username=username).first()

    if not user or not user.check_password(password):
        attempts.append(now)
        login_attempts[limiter_key] = attempts
        return jsonify({'error': '用户名或密码错误'}), 401

    login_attempts.pop(limiter_key, None)
    session['user_id'] = user.id
    session['username'] = user.username
    session['display_name'] = user.get_display_name()

    return jsonify({'message': '登录成功', 'user': user.to_dict()})


@app.route('/api/logout', methods=['POST'])
def logout():
    """退出登录"""
    session.clear()
    return jsonify({'message': '已退出登录'})


@app.route('/api/me')
def me():
    """获取当前用户信息"""
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify({'user': user.to_dict()})


# ==================== 路由：API - 管理员 ====================

@app.route('/api/admin/users')
@admin_required
def admin_list_users():
    """获取所有用户列表"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    pagination = User.query.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page)

    # 获取每个用户的统计信息
    users_data = []
    for user in pagination.items:
        user_dict = user.to_dict()
        user_dict['diary_count'] = Diary.query.filter_by(user_id=user.id).count()
        user_dict['conversation_count'] = Conversation.query.filter_by(user_id=user.id).count()
        user_dict['last_activity'] = None

        # 获取最后活动时间
        last_diary = Diary.query.filter_by(user_id=user.id).order_by(Diary.created_at.desc()).first()
        if last_diary:
            user_dict['last_activity'] = last_diary.created_at.isoformat()

        users_data.append(user_dict)

    return jsonify({
        'users': users_data,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@app.route('/api/admin/user/<int:user_id>')
@admin_required
def admin_get_user(user_id):
    """获取指定用户的详细信息"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    user_dict = user.to_dict()

    # 获取用户的日记列表
    diaries = Diary.query.filter_by(user_id=user_id)\
        .order_by(Diary.date.desc())\
        .limit(50)\
        .all()

    # 获取用户的对话历史
    conversations = Conversation.query.filter_by(user_id=user_id)\
        .order_by(Conversation.created_at.desc())\
        .limit(50)\
        .all()

    user_dict['diaries'] = [d.to_dict() for d in diaries]
    user_dict['conversations'] = [c.to_dict() for c in conversations]
    user_dict['diary_count'] = len(diaries)
    user_dict['conversation_count'] = len(conversations)

    return jsonify({'user': user_dict})


@app.route('/api/admin/user/<int:user_id>/diaries')
@admin_required
def admin_get_user_diaries(user_id):
    """获取指定用户的所有日记"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    pagination = Diary.query.filter_by(user_id=user_id)\
        .order_by(Diary.date.desc())\
        .paginate(page=page, per_page=per_page)

    return jsonify({
        'user': user.to_dict(),
        'diaries': [d.to_dict(include_analysis=True) for d in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@app.route('/api/admin/user/<int:user_id>/set_admin', methods=['POST'])
@admin_required
def admin_set_admin(user_id):
    """设置或取消管理员权限"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    # 不允许修改自己的管理员状态
    if user_id == session['user_id']:
        return jsonify({'error': '不能修改自己的管理员权限'}), 400

    data = request.get_json()
    is_admin = data.get('is_admin', False)

    user.is_admin = is_admin
    db.session.commit()

    return jsonify({
        'message': '管理员权限已更新',
        'user': user.to_dict()
    })


@app.route('/api/admin/stats')
@admin_required
def admin_stats():
    """获取系统统计信息"""
    from sqlalchemy import func

    total_users = User.query.count()
    total_diaries = Diary.query.count()
    total_conversations = Conversation.query.count()
    total_analyses = Analysis.query.count()

    # 最近活跃用户（7天内有日记）
    from datetime import timedelta
    week_ago = datetime.now() - timedelta(days=7)
    active_users = db.session.query(Diary.user_id)\
        .filter(Diary.created_at >= week_ago)\
        .distinct()\
        .count()

    # 今日注册用户
    today = datetime.now().date()
    today_users = User.query.filter(
        func.date(User.created_at) == today
    ).count()

    # 今日新增日记
    today_diaries = Diary.query.filter(
        func.date(Diary.created_at) == today
    ).count()

    return jsonify({
        'total_users': total_users,
        'total_diaries': total_diaries,
        'total_conversations': total_conversations,
        'total_analyses': total_analyses,
        'active_users_week': active_users,
        'today_users': today_users,
        'today_diaries': today_diaries
    })


@app.route('/api/admin/ai-config')
@admin_required
def admin_get_ai_config():
    """Return masked built-in AI configuration for the settings UI."""
    api_key = app.config.get('ANTHROPIC_API_KEY', '')
    return jsonify({
        'anthropic_base_url': app.config.get('ANTHROPIC_BASE_URL', ''),
        'anthropic_api_key_configured': bool(api_key),
        'anthropic_api_key_masked': mask_secret(api_key),
        'ai_available': bool(four_sages_engine and four_sages_engine.is_available())
    })


@app.route('/api/admin/ai-config', methods=['PUT'])
@admin_required
def admin_update_ai_config():
    """Update built-in AI API config and hot-reload the engine."""
    data = request.get_json(silent=True) or {}
    values = {}

    if 'anthropic_base_url' in data:
        values['ANTHROPIC_BASE_URL'] = data.get('anthropic_base_url', '')

    api_key = (data.get('anthropic_api_key') or '').strip()
    if api_key:
        values['ANTHROPIC_API_KEY'] = api_key
    elif data.get('clear_anthropic_api_key') is True:
        values['ANTHROPIC_API_KEY'] = ''

    if not values:
        return jsonify({'error': '没有需要保存的配置'}), 400

    try:
        apply_ai_runtime_config(values)
    except Exception as exc:
        logger.exception("更新AI配置失败")
        return jsonify({'error': f'AI配置保存失败：{exc.__class__.__name__}'}), 500

    api_key = app.config.get('ANTHROPIC_API_KEY', '')
    return jsonify({
        'message': 'AI配置已保存并热重载',
        'anthropic_base_url': app.config.get('ANTHROPIC_BASE_URL', ''),
        'anthropic_api_key_configured': bool(api_key),
        'anthropic_api_key_masked': mask_secret(api_key),
        'ai_available': bool(four_sages_engine and four_sages_engine.is_available())
    })


# ==================== 路由：API - 对话 ====================

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    """AI对话"""
    data = request.get_json()
    message = data.get('message', '').strip()
    style = data.get('style', 'four_sages')  # 获取风格参数，默认四圣谏言
    custom_style_prompt = data.get('custom_style_prompt', '').strip()
    images = data.get('images', [])  # 获取图片URL列表

    logger.info(f"收到聊天请求 - 消息: {message[:50]}..., 图片: {len(images)} 张, 图片URLs: {images}")

    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    # 保存用户消息
    user_msg = Conversation(
        user_id=session['user_id'],
        role='user',
        content=message
    )
    db.session.add(user_msg)
    append_to_diary(
        session['user_id'],
        '用户记录',
        message,
        source='日记模式输入'
    )
    memory_changes = sync_memory_from_message(session['user_id'], message)
    history_added = ensure_memory_from_history(session['user_id'], force=True) if is_memory_question(message) else []

    # 获取对话历史（用于AI上下文）
    conversations = Conversation.query.filter_by(
        user_id=session['user_id']
    ).order_by(Conversation.created_at.desc()).limit(20).all()

    conversation_history = [msg.to_dict() for msg in reversed(conversations[:-1])]  # 排除刚添加的消息

    if is_memory_question(message):
        ai_response = {'stage': 'memory_lookup', 'can_save': False}
        assistant_reply = format_open_memory_answer(session['user_id'], history_added=history_added)
    else:
        memory_context = format_memory_context(session['user_id'])
        ai_message = message
        if memory_context:
            ai_message = f"{message}\n\n{memory_context}\n请在合适时提醒用户这些未完成事项，但不要机械重复。"

        # 调用AI引擎（传入user_id以获取用户上下文，style以确定回复风格，images参数）
        ai_response = four_sages_engine.chat(
            ai_message,
            conversation_history,
            user_id=session.get('user_id'),
            style=style,
            images=images,
            custom_style_prompt=custom_style_prompt
        )
        assistant_reply = ai_response.get('reply', '抱歉，我现在无法回复。')

    if should_show_memory_reminder(message, memory_changes) and not is_memory_question(message):
        memory_prefix = build_memory_reply_prefix(session['user_id'], memory_changes)
        if memory_prefix:
            assistant_reply = f"{memory_prefix}\n\n{assistant_reply}"

    # 保存助手回复
    assistant_msg = Conversation(
        user_id=session['user_id'],
        role='assistant',
        content=assistant_reply
    )
    db.session.add(assistant_msg)
    append_to_diary(
        session['user_id'],
        'AI回应',
        assistant_reply,
        source=f'AI风格：{style}'
    )
    db.session.commit()

    return jsonify({
        'reply': assistant_reply,
        'stage': ai_response.get('stage', 'chatting'),
        'can_save': ai_response.get('can_save', False),
        'memory': {
            'added': [item.to_dict() for item in memory_changes.get('added', [])],
            'closed': [item.to_dict() for item in memory_changes.get('closed', [])],
            'history_added': [item.to_dict() for item in history_added],
            'open': [item.to_dict() for item in get_open_memory_items(session['user_id'], limit=5)]
        },
        'timestamp': datetime.now().isoformat()
    })


def sse_message(event, payload):
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.route('/api/chat/stream', methods=['POST'])
@login_required
def chat_stream():
    """AI对话流式接口。"""
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    style = data.get('style', 'four_sages')
    custom_style_prompt = data.get('custom_style_prompt', '').strip()
    images = data.get('images', [])
    user_id = session['user_id']

    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    logger.info(f"收到流式聊天请求 - 消息: {message[:50]}..., 图片: {len(images)} 张")

    user_msg = Conversation(
        user_id=user_id,
        role='user',
        content=message
    )
    db.session.add(user_msg)
    append_to_diary(
        user_id,
        '用户记录',
        message,
        source='日记模式输入'
    )
    memory_changes = sync_memory_from_message(user_id, message)
    history_added = ensure_memory_from_history(user_id, force=True) if is_memory_question(message) else []
    db.session.flush()

    conversations = Conversation.query.filter_by(
        user_id=user_id
    ).order_by(Conversation.created_at.desc()).limit(20).all()
    conversation_history = [msg.to_dict() for msg in reversed(conversations[:-1])]

    memory_payload = {
        'added': [item.to_dict() for item in memory_changes.get('added', [])],
        'closed': [item.to_dict() for item in memory_changes.get('closed', [])],
        'history_added': [item.to_dict() for item in history_added],
        'open': [item.to_dict() for item in get_open_memory_items(user_id, limit=5)]
    }

    @stream_with_context
    def generate():
        assistant_reply = ''
        ai_stage = 'chatting'
        can_save = False
        try:
            yield sse_message('meta', {
                'stage': ai_stage,
                'can_save': can_save,
                'memory': memory_payload,
                'timestamp': datetime.now().isoformat()
            })

            if is_memory_question(message):
                ai_stage = 'memory_lookup'
                text = format_open_memory_answer(user_id, history_added=history_added)
                assistant_reply = text
                # 分段输出，避免移动端突然出现一整屏文字。
                for paragraph in re.split(r'(\n+)', text):
                    if paragraph:
                        yield sse_message('delta', {'text': paragraph})
            else:
                memory_context = format_memory_context(user_id)
                ai_message = message
                if memory_context:
                    ai_message = f"{message}\n\n{memory_context}\n请在合适时提醒用户这些未完成事项，但不要机械重复。"

                memory_prefix = ''
                if should_show_memory_reminder(message, memory_changes):
                    memory_prefix = build_memory_reply_prefix(user_id, memory_changes)
                    if memory_prefix:
                        prefix_chunk = f"{memory_prefix}\n\n"
                        assistant_reply += prefix_chunk
                        yield sse_message('delta', {'text': prefix_chunk})

                for chunk in four_sages_engine.stream_chat(
                    ai_message,
                    conversation_history,
                    user_id=user_id,
                    style=style,
                    images=images,
                    custom_style_prompt=custom_style_prompt
                ):
                    assistant_reply += chunk
                    yield sse_message('delta', {'text': chunk})

            assistant_msg = Conversation(
                user_id=user_id,
                role='assistant',
                content=assistant_reply
            )
            db.session.add(assistant_msg)
            append_to_diary(
                user_id,
                'AI回应',
                assistant_reply,
                source=f'AI风格：{style}'
            )
            db.session.commit()
            yield sse_message('done', {
                'reply': assistant_reply,
                'stage': ai_stage,
                'can_save': can_save,
                'memory': memory_payload,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as exc:
            db.session.rollback()
            logger.exception("流式聊天失败: %s", exc)
            yield sse_message('error', {'error': 'AI回复生成失败，请稍后重试。'})

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Connection'] = 'keep-alive'
    return response


@app.route('/api/conversation')
@login_required
def get_conversation():
    """获取对话历史"""
    limit = request.args.get('limit', 50, type=int)
    conversations = Conversation.query.filter_by(
        user_id=session['user_id']
    ).order_by(Conversation.created_at.desc()).limit(limit).all()

    return jsonify({
        'messages': [msg.to_dict() for msg in reversed(conversations)]
    })


@app.route('/api/conversation/clear', methods=['POST'])
@login_required
def clear_conversation():
    """清理对话历史"""
    try:
        # 删除用户的所有对话记录
        Conversation.query.filter_by(
            user_id=session['user_id']
        ).delete()
        db.session.commit()
        return jsonify({'message': '对话已清理'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/memory/open')
@login_required
def list_open_memory():
    """获取当前用户未完成记忆事项。"""
    items = get_open_memory_items(session['user_id'], limit=request.args.get('limit', 20, type=int))
    return jsonify({'items': [item.to_dict() for item in items]})


@app.route('/api/memory/<int:item_id>/done', methods=['POST'])
@login_required
def mark_memory_done(item_id):
    """手动标记记忆事项完成。"""
    item = MemoryItem.query.filter_by(id=item_id, user_id=session['user_id']).first()
    if not item:
        return jsonify({'error': '事项不存在'}), 404
    item.status = 'done'
    item.updated_at = datetime.now()
    db.session.commit()
    return jsonify({'item': item.to_dict(), 'message': '已标记完成'})


# ==================== 路由：API - 日记 ====================

@app.route('/api/diary', methods=['POST'])
@login_required
def save_diary():
    """保存日记"""
    data = request.get_json()
    content = data.get('content', '').strip()
    date = data.get('date', datetime.now().strftime('%Y-%m-%d'))

    if not content:
        return jsonify({'error': '日记内容不能为空'}), 400

    # 检查当天是否已有日记
    existing = Diary.query.filter_by(
        user_id=session['user_id'],
        date=date
    ).first()

    if existing:
        existing.content = content
        existing.updated_at = datetime.now()
        diary = existing
    else:
        diary = Diary(
            user_id=session['user_id'],
            date=date,
            content=content
        )
        db.session.add(diary)

    db.session.commit()

    return jsonify({
        'message': '日记已保存',
        'diary': diary.to_dict()
    })


@app.route('/api/diary/today/summary', methods=['POST'])
@login_required
def summarize_today_diary():
    """手动生成当天战略总结，并写回当天日记。"""
    data = request.get_json(silent=True) or {}
    style = data.get('style', 'four_sages')
    custom_style_prompt = data.get('custom_style_prompt', '').strip()

    summary = generate_today_summary_text(session['user_id'], style=style, custom_style_prompt=custom_style_prompt)
    diary = append_to_diary(
        session['user_id'],
        '今日战略总结',
        summary,
        source=f'手动总结 / {style}'
    )
    db.session.commit()

    return jsonify({
        'summary': summary,
        'diary': diary.to_dict() if diary else None
    })


@app.route('/api/diary/list')
@login_required
def diary_list():
    """获取日记列表"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', app.config['DIARIES_PER_PAGE'], type=int)

    pagination = Diary.query.filter_by(
        user_id=session['user_id']
    ).order_by(Diary.date.desc()).paginate(page=page, per_page=per_page)

    return jsonify({
        'diaries': [d.to_dict() for d in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@app.route('/api/diary/search')
@login_required
def diary_search():
    """搜索日记"""
    keyword = request.args.get('keyword', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', app.config['DIARIES_PER_PAGE'], type=int)

    if not keyword:
        return jsonify({'error': '关键词不能为空'}), 400

    # 搜索包含关键词的日记
    query = Diary.query.filter_by(user_id=session['user_id'])\
        .filter(Diary.content.contains(keyword))

    # 分页
    pagination = query.order_by(Diary.date.desc()).paginate(page=page, per_page=per_page)

    return jsonify({
        'results': [d.to_dict() for d in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@app.route('/api/diary/<int:diary_id>')
@login_required
def diary_detail(diary_id):
    """获取日记详情"""
    diary = Diary.query.filter_by(
        id=diary_id,
        user_id=session['user_id']
    ).first()

    if not diary:
        return jsonify({'error': '日记不存在'}), 404

    return jsonify({'diary': diary.to_dict(include_analysis=True)})


@app.route('/api/analyze', methods=['POST'])
@login_required
def analyze_text():
    """分析文本"""
    data = request.get_json()
    content = data.get('content', '').strip()

    if not content:
        return jsonify({'error': '内容不能为空'}), 400

    # 调用分析器
    result = diary_analyzer.analyze(content)

    return jsonify({
        'analysis': result
    })


# ==================== 路由：API - 智能问答 ====================

@app.route('/api/query', methods=['POST'])
@login_required
def query_diaries():
    """智能问答 - 搜索和分析日记"""
    data = request.get_json()
    question = data.get('question', '').strip()
    style = data.get('style', 'four_sages')
    custom_style_prompt = data.get('custom_style_prompt', '').strip()

    if not question:
        return jsonify({'error': '问题不能为空'}), 400

    if not query_engine:
        return jsonify({'error': '问答引擎未初始化'}), 500

    interview_keywords = ['面试', '评价', '复盘', '短板', '趋势', '表达', '答题']
    if any(keyword in question for keyword in interview_keywords):
        trend_context = build_interview_trend_context(session['user_id'], limit=12)
        prompt = f"""用户正在查询自己的历史记录和面试训练趋势。

问题：{question}

可用的面试评价趋势：
{trend_context}

请结合趋势给出回答。要求：先客观说事实，再给下一步训练建议；语气温柔鼓励，但不要空泛。"""
        ai_result = four_sages_engine.chat(
            prompt,
            user_id=session.get('user_id'),
            style=style,
            custom_style_prompt=custom_style_prompt
        )
        return jsonify({
            'answer': ai_result.get('reply') or trend_context,
            'type': 'interview_trend',
            'sources': []
        })

    if is_memory_question(question):
        ensure_memory_from_history(session['user_id'], force=True)

    # 调用问答引擎
    result = query_engine.answer(question, session.get('user_id'))

    return jsonify({
        'answer': result.get('answer'),
        'type': result.get('type'),
        'sources': result.get('sources', [])
    })


@app.route('/api/diary/<int:diary_id>/analyze', methods=['POST'])
@login_required
def analyze_diary(diary_id):
    """分析日记并保存结果"""
    diary = Diary.query.filter_by(
        id=diary_id,
        user_id=session['user_id']
    ).first()

    if not diary:
        return jsonify({'error': '日记不存在'}), 404

    # 调用分析器
    result = diary_analyzer.analyze(diary.content)

    # 保存或更新分析结果
    analysis = Analysis.query.filter_by(diary_id=diary_id).first()

    if analysis:
        analysis.emotion = result.get('emotion')
        analysis.set_keywords(result.get('keywords', []))
        analysis.set_four_sages(result.get('four_sages', {}))
        analysis.full_analysis = result.get('full_report')
        analysis.suggestions = result.get('suggestions')
    else:
        analysis = Analysis(
            diary_id=diary_id,
            emotion=result.get('emotion'),
            suggestions=result.get('suggestions'),
            full_analysis=result.get('full_report')
        )
        analysis.set_keywords(result.get('keywords', []))
        analysis.set_four_sages(result.get('four_sages', {}))
        db.session.add(analysis)

    db.session.commit()

    return jsonify({
        'message': '分析完成',
        'analysis': analysis.to_dict()
    })


# ==================== 路由：API - 图片上传 ====================

def file_extension(filename):
    if '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def allowed_file(filename, allowed_extensions=None):
    allowed_extensions = allowed_extensions or ALLOWED_EXTENSIONS
    return file_extension(filename) in allowed_extensions

@app.route('/api/upload/image', methods=['POST'])
@login_required
def upload_image():
    """上传图片"""
    if 'image' not in request.files:
        return jsonify({'error': '没有文件'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': '不支持的文件类型'}), 400

    try:
        # 生成安全的文件名
        filename = secure_filename(file.filename)
        # 添加时间戳避免冲突
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        name, ext = os.path.splitext(filename)
        filename = f"{timestamp}_{name}{ext}"

        # 保存文件
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        # 返回URL
        url = f"/static/uploads/{filename}"
        return jsonify({'url': url})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/upload/background', methods=['POST'])
@login_required
def upload_chat_background():
    """上传对话背景图片"""
    # 检查是否是纯色背景设置
    if request.is_json:
        data = request.get_json()
        color = data.get('color')
        if color:
            user = User.query.get(session['user_id'])
            if user:
                user.chat_background = None  # 清除图片背景
                user.background_color = color
                db.session.commit()
            return jsonify({'color': color})

    # 图片上传处理
    if 'background' not in request.files:
        return jsonify({'error': '没有文件'}), 400

    file = request.files['background']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': '不支持的文件类型，请使用 JPG、PNG、GIF'}), 400

    try:
        # 生成安全的文件名
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        name, ext = os.path.splitext(filename)
        filename = f"bg_{timestamp}_{name}{ext}"

        # 保存文件
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        # 更新用户的背景设置
        url = f"/static/uploads/{filename}"
        user = User.query.get(session['user_id'])
        if user:
            user.chat_background = url
            user.background_color = None  # 清除纯色背景
            db.session.commit()

        return jsonify({'url': url})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/voice/transcribe', methods=['POST'])
@login_required
def transcribe_voice():
    """服务器端语音转文字兜底。当前支持 OpenAI 兼容转写接口。"""
    if 'audio' not in request.files:
        return jsonify({'error': '缺少音频文件'}), 400

    provider = app.config.get('SPEECH_TO_TEXT_PROVIDER', '')
    if provider not in {'openai'}:
        return jsonify({
            'error': '服务器端语音转文字未配置',
            'hint': '可在 .env 中设置 SPEECH_TO_TEXT_PROVIDER=openai、OPENAI_API_KEY，配置后将用后端转写替代浏览器识别。'
        }), 501

    api_key = app.config.get('OPENAI_API_KEY', '')
    if not api_key:
        return jsonify({'error': 'OPENAI_API_KEY 未配置，无法使用服务器端语音转文字'}), 501

    audio = request.files['audio']
    if not audio.filename:
        return jsonify({'error': '音频文件名为空'}), 400
    if not allowed_file(audio.filename, ALLOWED_AUDIO_EXTENSIONS):
        return jsonify({'error': '不支持的音频格式'}), 400

    import tempfile
    import urllib.request
    import uuid

    suffix = '.' + file_extension(audio.filename)
    temp_path = None
    boundary = '----DiaryVoiceBoundary' + uuid.uuid4().hex
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            audio.save(tmp)
            temp_path = tmp.name

        with open(temp_path, 'rb') as f:
            audio_bytes = f.read()

        model = app.config.get('OPENAI_TRANSCRIBE_MODEL', 'gpt-4o-mini-transcribe')
        body = b''.join([
            (
                f'--{boundary}\r\n'
                'Content-Disposition: form-data; name="model"\r\n\r\n'
                f'{model}\r\n'
            ).encode('utf-8'),
            (
                f'--{boundary}\r\n'
                'Content-Disposition: form-data; name="language"\r\n\r\n'
                'zh\r\n'
            ).encode('utf-8'),
            (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="file"; filename="{secure_filename(audio.filename)}"\r\n'
                f'Content-Type: {audio.mimetype or "application/octet-stream"}\r\n\r\n'
            ).encode('utf-8'),
            audio_bytes,
            f'\r\n--{boundary}--\r\n'.encode('utf-8')
        ])
        url = app.config.get('OPENAI_BASE_URL').rstrip('/') + '/audio/transcriptions'
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': f'multipart/form-data; boundary={boundary}',
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode('utf-8'))

        return jsonify({'text': (payload.get('text') or '').strip(), 'provider': provider})
    except Exception as e:
        logger.error(f"服务器端语音转文字失败: {e}")
        return jsonify({'error': '服务器端语音转文字失败', 'detail': str(e)}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@app.route('/api/user/background', methods=['GET', 'DELETE', 'POST'])
@login_required
def user_background():
    """获取、设置或删除用户背景"""
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    if request.method == 'DELETE':
        user.chat_background = None
        user.background_color = None
        db.session.commit()
        return jsonify({'message': '背景已移除'})

    if request.method == 'POST':
        data = request.get_json() if request.is_json else {}
        color = data.get('color')
        if color:
            user.chat_background = None
            user.background_color = color
            db.session.commit()
            return jsonify({'color': color})

    return jsonify({
        'background': user.chat_background,
        'background_color': user.background_color
    })


# ==================== 路由：API - 情绪数据 ====================

@app.route('/api/emotion/data')
@login_required
def get_emotion_data():
    """获取情绪数据用于图表展示"""
    days = request.args.get('days', 30, type=int)
    limit = min(days, 365)  # 最多365天

    # 获取最近的日记及其分析
    diaries = Diary.query.filter(
        Diary.user_id == session['user_id']
    ).order_by(Diary.date.desc()).limit(limit).all()

    data = []
    for diary in diaries:
        emotion = None
        if diary.analysis:
            emotion = diary.analysis.emotion

        # 如果没有分析结果，尝试简单判断
        if not emotion:
            content = diary.content.lower()
            if any(w in content for w in ['开心', '快乐', '顺利', '完成', '成功']):
                emotion = 'positive'
            elif any(w in content for w in ['难过', '累', '失败', '挫折']):
                emotion = 'negative'
            else:
                emotion = 'neutral'

        data.append({
            'date': diary.date,
            'emotion': emotion
        })

    # 按日期排序（旧到新）
    data.reverse()

    return jsonify({'data': data})


@app.route('/api/diaries')
@login_required
def get_diaries_list():
    """获取用户所有日记列表（用于日历视图）"""
    diaries = Diary.query.filter(
        Diary.user_id == session['user_id']
    ).order_by(Diary.date.desc()).all()

    return jsonify({
        'diaries': [d.to_dict() for d in diaries]
    })


# ==================== 路由：API - 周报月报 ====================

@app.route('/api/report/<period>')
@login_required
def generate_report(period):
    """生成周报或月报

    Args:
        period: 'weekly' 或 'monthly'
    """
    if period not in ['weekly', 'monthly']:
        return jsonify({'error': '无效的时间周期'}), 400

    from datetime import timedelta

    # 确定时间范围
    if period == 'weekly':
        days = 7
        title = '周报'
    else:
        days = 30
        title = '月报'

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # 获取时间范围内的日记
    diaries = Diary.query.filter(
        Diary.user_id == session['user_id'],
        Diary.date >= start_date.strftime('%Y-%m-%d'),
        Diary.date <= end_date.strftime('%Y-%m-%d')
    ).order_by(Diary.date.asc()).all()

    if not diaries:
        return jsonify({'error': f'{title}时间范围内没有日记记录'}), 404

    # 使用AI生成报告
    try:
        # 准备日记内容摘要
        diary_summary = []
        for diary in diaries:
            content = diary.content[:200]  # 限制长度
            diary_summary.append(f"## {diary.date}\n{content}")

        prompt = f"""请根据以下{days}天的日记内容，生成一份{title}。

日记内容：
{''.join(diary_summary)}

请生成一份结构化的{title}，包含：
1. 整体概述
2. 情绪变化趋势
3. 重要事件回顾
4. 个人成长/反思
5. 下阶段建议

请使用Markdown格式，温柔且鼓励的语气。"""

        response = four_sages_engine.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        report = response.content[0].text

        return jsonify({
            'period': period,
            'title': title,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'diary_count': len(diaries),
            'report': report
        })

    except Exception as e:
        logger.error(f"生成{title}失败: {e}")
        # 降级：返回简单的统计
        return jsonify({
            'period': period,
            'title': title,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'diary_count': len(diaries),
            'report': f"## {title}\n\n时间范围：{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}\n\n记录天数：{len(diaries)}天\n\n（AI报告生成失败，请稍后重试）"
        })


# ==================== 路由：API - 话题推荐 ====================

@app.route('/api/topics/recommendations')
@login_required
def get_topic_recommendations():
    """获取话题推荐 - 基于最近日记分析忽视的记录方向"""
    try:
        recommendations = four_sages_engine.get_topic_recommendations(session.get('user_id'))
        return jsonify({'recommendations': recommendations})
    except Exception as e:
        logger.error(f"获取话题推荐失败: {e}")
        return jsonify({'recommendations': four_sages_engine._default_recommendations()})


# ==================== 路由：API - 日报推送 ====================

@app.route('/api/report/config', methods=['GET'])
@login_required
def get_report_config():
    """获取日报推送配置"""
    config = ReportConfig.query.filter_by(user_id=session['user_id']).first()

    if not config:
        # 创建默认配置
        config = ReportConfig(user_id=session['user_id'])
        db.session.add(config)
        db.session.commit()

    return jsonify({'config': config.to_dict()})


@app.route('/api/report/config', methods=['POST'])
@login_required
def update_report_config():
    """更新日报推送配置"""
    data = request.get_json()

    config = ReportConfig.query.filter_by(user_id=session['user_id']).first()

    if not config:
        config = ReportConfig(user_id=session['user_id'])
        db.session.add(config)

    # 更新配置
    if 'topics' in data:
        config.set_topics(data['topics'])
    if 'custom_topics' in data:
        config.set_custom_topics(data['custom_topics'])
    if 'push_time' in data:
        config.push_time = data['push_time']
    if 'timezone' in data:
        config.timezone = data['timezone']
    if 'enabled' in data:
        config.enabled = data['enabled']

    db.session.commit()

    today_report = None
    today_report_generated = False
    if config.enabled and report_generator:
        today = datetime.now().strftime('%Y-%m-%d')
        existing = DailyReport.query.filter_by(
            user_id=session['user_id'],
            report_date=today
        ).order_by(DailyReport.created_at.desc()).first()
        if existing:
            today_report = existing.to_dict()
        else:
            try:
                result = report_generator.generate(session['user_id'], config.get_topics())
                if not result.get('error'):
                    today_report_generated = True
                    report = DailyReport.query.get(result.get('report_id'))
                    today_report = report.to_dict() if report else None
            except Exception as e:
                logger.warning(f"保存日报配置后自动生成今日日报失败: {e}")

    return jsonify({
        'message': '配置已更新',
        'config': config.to_dict(),
        'today_report_generated': today_report_generated,
        'today_report': today_report
    })


@app.route('/api/report/today')
@login_required
def get_or_generate_today_report():
    """获取今天的日报；可在缺失时按配置自动生成。"""
    ensure = request.args.get('ensure', 'false').lower() == 'true'
    today = datetime.now().strftime('%Y-%m-%d')

    report = DailyReport.query.filter_by(
        user_id=session['user_id'],
        report_date=today
    ).order_by(DailyReport.created_at.desc()).first()

    if report:
        return jsonify({
            'report': report.to_dict(),
            'generated': False,
            'ready': True
        })

    config = ReportConfig.query.filter_by(user_id=session['user_id']).first()
    if not ensure or not config or not config.enabled:
        return jsonify({
            'report': None,
            'generated': False,
            'ready': False
        })

    if not report_generator:
        return jsonify({'error': '报告生成器未初始化'}), 500

    try:
        result = report_generator.generate(session['user_id'], config.get_topics())
        if result.get('error'):
            return jsonify({'error': result['error']}), 400
        report = DailyReport.query.get(result.get('report_id'))
        return jsonify({
            'report': report.to_dict() if report else None,
            'generated': True,
            'ready': True
        })
    except Exception as e:
        logger.error(f"自动生成今日日报失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/generate', methods=['POST'])
@login_required
def generate_daily_report():
    """生成日报"""
    data = request.get_json() or {}
    topics = data.get('topics')  # 可选的自定义话题

    if not report_generator:
        return jsonify({'error': '报告生成器未初始化'}), 500

    try:
        result = report_generator.generate(session['user_id'], topics)
        return jsonify(result)
    except Exception as e:
        logger.error(f"生成日报失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/report/history')
@login_required
def get_report_history():
    """获取历史报告"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    pagination = DailyReport.query.filter_by(
        user_id=session['user_id']
    ).order_by(DailyReport.report_date.desc()).paginate(page=page, per_page=per_page)

    return jsonify({
        'reports': [r.to_dict() for r in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@app.route('/api/report/<int:report_id>')
@login_required
def get_report_detail(report_id):
    """获取报告详情"""
    report = DailyReport.query.filter_by(
        id=report_id,
        user_id=session['user_id']
    ).first()

    if not report:
        return jsonify({'error': '报告不存在'}), 404

    return jsonify({'report': report.to_dict()})


# ==================== 考公复盘系统路由 ====================

@app.route('/kaogong')
def kaogong_page():
    """考公复盘页面"""
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    if not is_user_feature_enabled(session['user_id'], 'kaogong'):
        return redirect(url_for('settings_page'))
    return render_template('kaogong.html', username=current_display_name(), features=get_feature_flags(session['user_id']))


@app.route('/settings')
def settings_page():
    """设置页面"""
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    user = User.query.get(session['user_id'])
    return render_template(
        'settings.html',
        username=current_display_name(),
        features=get_feature_flags(session['user_id']),
        is_admin=bool(user and user.is_admin)
    )


# ==================== 行测题目相关API ====================

@app.route('/api/kaogong/xingce/question', methods=['POST'])
@login_required
def add_xingce_question():
    """添加行测题目"""
    data = request.get_json()

    from models import XingceQuestion, XingceStatistics

    question = XingceQuestion(
        user_id=session['user_id'],
        question_type=data.get('question_type', 'verbal'),
        content=data.get('content', ''),
        options=data.get('options', [])
    )
    question.set_options(data.get('options', []))

    if 'correct_answer' in data:
        question.correct_answer = data['correct_answer']
    if 'user_answer' in data:
        question.user_answer = data['user_answer']
    if 'is_correct' in data:
        question.is_correct = data['is_correct']
    if 'time_spent' in data:
        question.time_spent = data['time_spent']
    if 'analysis' in data:
        question.analysis = data['analysis']
    if 'source' in data:
        question.source = data['source']
    if 'image_url' in data:
        question.image_url = data['image_url']

    if 'tags' in data:
        question.set_tags(data['tags'])

    db.session.add(question)
    db.session.commit()

    # 更新统计数据
    _update_xingce_stats(session['user_id'], question)

    return jsonify({'question': question.to_dict()})


@app.route('/api/kaogong/xingce/questions')
@login_required
def get_xingce_questions():
    """获取行测题目列表"""
    from models import XingceQuestion

    # 筛选条件
    question_type = request.args.get('type')
    is_correct = request.args.get('correct')
    is_wrong = request.args.get('wrong')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))

    query = XingceQuestion.query.filter_by(user_id=session['user_id'])

    if question_type:
        query = query.filter_by(question_type=question_type)
    if is_correct == 'true':
        query = query.filter_by(is_correct=True)
    if is_wrong == 'true':
        query = query.filter_by(is_correct=False)

    # 分页
    pagination = query.order_by(XingceQuestion.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'questions': [q.to_dict() for q in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@app.route('/api/kaogong/xingce/question/<int:question_id>', methods=['PUT'])
@login_required
def update_xingce_question(question_id):
    """更新行测题目"""
    from models import XingceQuestion, XingceStatistics

    question = XingceQuestion.query.filter_by(
        id=question_id,
        user_id=session['user_id']
    ).first()

    if not question:
        return jsonify({'error': '题目不存在'}), 404

    data = request.get_json()

    if 'user_answer' in data:
        question.user_answer = data['user_answer']
    if 'is_correct' in data:
        question.is_correct = data['is_correct']
    if 'time_spent' in data:
        question.time_spent = data['time_spent']
    if 'analysis' in data:
        question.analysis = data['analysis']
    if 'tags' in data:
        question.set_tags(data['tags'])

    question.reviewed_at = datetime.now()
    db.session.commit()

    # 更新统计数据
    _update_xingce_stats(session['user_id'], question)

    return jsonify({'question': question.to_dict()})


@app.route('/api/kaogong/xingce/question/<int:question_id>', methods=['DELETE'])
@login_required
def delete_xingce_question(question_id):
    """删除行测题目"""
    from models import XingceQuestion

    question = XingceQuestion.query.filter_by(
        id=question_id,
        user_id=session['user_id']
    ).first()

    if not question:
        return jsonify({'error': '题目不存在'}), 404

    db.session.delete(question)
    db.session.commit()
    _update_xingce_stats(session['user_id'])

    return jsonify({'message': '删除成功'})


@app.route('/api/kaogong/xingce/statistics')
@login_required
def get_xingce_statistics():
    """获取行测统计数据"""
    from models import XingceStatistics

    stats = XingceStatistics.query.filter_by(user_id=session['user_id']).first()

    if not stats:
        stats = XingceStatistics(user_id=session['user_id'])
        db.session.add(stats)
        db.session.commit()

    return jsonify({'statistics': stats.to_dict()})


def _update_xingce_stats(user_id, question=None):
    """按当前题库重算行测统计，避免编辑/删除后出现重复计数。"""
    from models import XingceStatistics

    stats = XingceStatistics.query.filter_by(user_id=user_id).first()
    if not stats:
        stats = XingceStatistics(user_id=user_id)
        db.session.add(stats)

    type_mapping = {
        'verbal': ('verbal_total', 'verbal_correct'),
        'quantitative': ('quantitative_total', 'quantitative_correct'),
        'reasoning': ('reasoning_total', 'reasoning_correct'),
        'data_analysis': ('data_analysis_total', 'data_analysis_correct'),
        'general': ('general_total', 'general_correct')
    }

    for total_field, correct_field in type_mapping.values():
        setattr(stats, total_field, 0)
        setattr(stats, correct_field, 0)

    questions = XingceQuestion.query.filter_by(user_id=user_id).all()
    for item in questions:
        if item.question_type not in type_mapping:
            continue
        total_field, correct_field = type_mapping[item.question_type]
        setattr(stats, total_field, getattr(stats, total_field, 0) + 1)
        if item.is_correct is True:
            setattr(stats, correct_field, getattr(stats, correct_field, 0) + 1)

    stats.total_questions = (stats.verbal_total + stats.quantitative_total +
                             stats.reasoning_total + stats.data_analysis_total +
                             stats.general_total)
    stats.total_correct = (stats.verbal_correct + stats.quantitative_correct +
                           stats.reasoning_correct + stats.data_analysis_correct +
                           stats.general_correct)
    stats.updated_at = datetime.now()

    db.session.commit()


# ==================== 面试复盘相关API ====================

@app.route('/api/kaogong/interview/record', methods=['POST'])
@login_required
def add_interview_record():
    """添加面试复盘记录"""
    from models import InterviewRecord

    data = request.get_json()

    record = InterviewRecord(
        user_id=session['user_id'],
        interview_type=data.get('interview_type', 'structured'),
        category=data.get('category', 'comprehensive'),
        question=data.get('question', ''),
        answer_text=data.get('answer_text', '')
    )

    if 'audio_url' in data:
        record.audio_url = data['audio_url']
    if 'duration' in data:
        record.duration = data['duration']
    if 'self_reflection' in data:
        record.self_reflection = data['self_reflection']
    if 'ai_evaluation' in data:
        record.set_ai_evaluation(data['ai_evaluation'])

    if 'tags' in data:
        record.set_tags(data['tags'])

    db.session.add(record)
    db.session.flush()

    diary_parts = [
        f"题型：{record.category}",
        f"题目：{record.question}",
        f"回答：{record.answer_text or '未填写'}"
    ]
    if record.duration:
        diary_parts.append(f"用时：{record.duration} 秒")
    if record.self_reflection:
        diary_parts.append(f"自我复盘：{record.self_reflection}")
    evaluation_text = format_interview_evaluation_for_diary(record.get_ai_evaluation())
    if evaluation_text:
        diary_parts.append("AI面试评价：\n" + evaluation_text)
    append_to_diary(
        session['user_id'],
        '面试复盘评价',
        "\n\n".join(diary_parts),
        source='考公面试训练'
    )
    db.session.commit()

    return jsonify({'record': record.to_dict()})


@app.route('/api/kaogong/interview/records')
@login_required
def get_interview_records():
    """获取面试复盘记录"""
    from models import InterviewRecord

    category = request.args.get('category')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))

    query = InterviewRecord.query.filter_by(user_id=session['user_id'])

    if category:
        query = query.filter_by(category=category)

    pagination = query.order_by(InterviewRecord.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'records': [r.to_dict() for r in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@app.route('/api/kaogong/interview/record/<int:record_id>', methods=['PUT'])
@login_required
def update_interview_record(record_id):
    """更新面试复盘记录"""
    from models import InterviewRecord

    record = InterviewRecord.query.filter_by(
        id=record_id,
        user_id=session['user_id']
    ).first()

    if not record:
        return jsonify({'error': '记录不存在'}), 404

    data = request.get_json()

    if 'self_reflection' in data:
        record.self_reflection = data['self_reflection']
    if 'ai_evaluation' in data:
        record.set_ai_evaluation(data['ai_evaluation'])
    if 'tags' in data:
        record.set_tags(data['tags'])

    if any(key in data for key in ['self_reflection', 'ai_evaluation', 'tags']):
        evaluation_text = format_interview_evaluation_for_diary(record.get_ai_evaluation())
        append_to_diary(
            session['user_id'],
            '面试复盘更新',
            f"题目：{record.question}\n\n自我复盘：{record.self_reflection or '未填写'}\n\nAI面试评价：\n{evaluation_text or '暂无'}",
            source='考公面试训练'
        )

    db.session.commit()

    return jsonify({'record': record.to_dict()})


@app.route('/api/kaogong/interview/trends')
@login_required
def get_interview_trends():
    """获取面试评价趋势，供AI和前端单独查看。"""
    return jsonify({
        'trend': build_interview_trend_context(session['user_id'], limit=20)
    })


@app.route('/api/kaogong/interview/record/<int:record_id>', methods=['DELETE'])
@login_required
def delete_interview_record(record_id):
    """删除面试复盘记录"""
    from models import InterviewRecord

    record = InterviewRecord.query.filter_by(
        id=record_id,
        user_id=session['user_id']
    ).first()

    if not record:
        return jsonify({'error': '记录不存在'}), 404

    db.session.delete(record)
    db.session.commit()

    return jsonify({'message': '删除成功'})


@app.route('/api/kaogong/interview/questions')
@login_required
def get_interview_questions():
    """获取面试题库"""
    from models import DEFAULT_INTERVIEW_QUESTIONS, INTERVIEW_CATEGORY_NAMES
    from interview_standards import get_category_guidance

    category = request.args.get('category')

    questions = DEFAULT_INTERVIEW_QUESTIONS
    if category:
        questions = [q for q in questions if q['category'] == category]

    result = []
    for q in questions:
        item = q.copy()
        guidance = get_category_guidance(item['category'])
        item['category_name'] = INTERVIEW_CATEGORY_NAMES.get(item['category'], item['category'])
        item['guidance'] = guidance
        item.setdefault('measured_elements', guidance['measured_elements'])
        item.setdefault('answer_framework', guidance['answer_framework'])
        item.setdefault('time_limit_seconds', guidance['time_limit_seconds'])
        item.setdefault('pitfalls', guidance['pitfalls'])
        result.append(item)

    return jsonify({'questions': result})


@app.route('/api/kaogong/interview/categories')
@login_required
def get_interview_categories():
    """获取面试分类列表"""
    from models import INTERVIEW_CATEGORY_NAMES

    return jsonify({'categories': [
        {'value': k, 'name': v} for k, v in INTERVIEW_CATEGORY_NAMES.items()
    ]})


@app.route('/api/kaogong/interview/standards')
@login_required
def get_interview_standards():
    """获取公务员面试方法、测评要素和题型训练映射。"""
    from interview_standards import (
        OFFICIAL_EVALUATION_DIMENSIONS, INTERVIEW_FORMATS, CATEGORY_GUIDANCE
    )

    return jsonify({
        'dimensions': OFFICIAL_EVALUATION_DIMENSIONS,
        'formats': INTERVIEW_FORMATS,
        'categories': CATEGORY_GUIDANCE,
        'sources': [
            {
                'title': '国家公务员录用面试暂行办法',
                'url': 'https://www.stats.gov.cn/fw/gwyzl/zlzc_19271/202302/t20230223_1918391.html'
            },
            {
                'title': '公务员录用面试组织管理办法（试行）',
                'url': 'https://www.gd.gov.cn/zwgk/wjk/zcfgk/content/mpost_2723797.html'
            },
            {
                'title': '中央机关及其直属机构2026年度考试录用公务员公告',
                'url': 'https://shanghai.chinatax.gov.cn/xxgk/rsxx/202510/t477989.html'
            }
        ]
    })


@app.route('/api/kaogong/interview/evaluate', methods=['POST'])
@login_required
def evaluate_interview():
    """AI评价面试回答 - 结合RAG知识库"""
    from interview_evaluator import InterviewEvaluator

    data = request.get_json()
    question = data.get('question', '')
    answer = data.get('answer', '')
    category = data.get('category', 'comprehensive')

    # 使用增强的评价器
    evaluator = InterviewEvaluator(ai_engine=four_sages_engine)
    evaluation = evaluator.evaluate(question, answer, category)

    return jsonify({'evaluation': evaluation})


@app.route('/api/kaogong/interview/suggestions')
@login_required
def get_interview_suggestions():
    """获取面试练习建议"""
    from interview_evaluator import InterviewCoach

    category = request.args.get('category', '')

    coach = InterviewCoach()

    if category:
        suggestions = coach.evaluator.get_practice_suggestions(category)
        return jsonify({'suggestions': suggestions})
    else:
        plan = coach.generate_practice_plan()
        return jsonify({'plan': plan})


@app.route('/api/kaogong/interview/weakness-analysis', methods=['POST'])
@login_required
def analyze_interview_weakness():
    """分析面试弱点"""
    from interview_evaluator import InterviewCoach

    data = request.get_json()
    history = data.get('history', [])

    coach = InterviewCoach()
    analysis = coach.get_weakness_improvement(history)

    return jsonify({'analysis': analysis})


@app.route('/api/kaogong/knowledge/stats')
@login_required
def get_knowledge_stats():
    """获取知识库统计"""
    from vector_store import get_knowledge_base

    kb = get_knowledge_base()
    stats = kb.get_stats()

    return jsonify({'stats': stats})


@app.route('/api/kaogong/knowledge/search', methods=['POST'])
@login_required
def search_knowledge():
    """搜索知识库"""
    from vector_store import get_knowledge_base

    data = request.get_json()
    query = data.get('query', '')
    category = data.get('category', '')
    top_k = data.get('top_k', 3)

    kb = get_knowledge_base()

    filter_dict = {"category": category} if category else None
    results = kb.search(query, top_k=top_k, filter_metadata=filter_dict)

    return jsonify({'results': results})


# ==================== 学习资料相关API ====================

@app.route('/api/kaogong/material', methods=['POST'])
@login_required
def add_study_material():
    """添加学习资料"""
    from models import StudyMaterial

    data = request.get_json()

    material = StudyMaterial(
        user_id=session['user_id'],
        title=data.get('title', ''),
        material_type=data.get('material_type', 'general'),
        file_url=data.get('file_url', ''),
        file_type=data.get('file_type', 'pdf')
    )

    if 'content_summary' in data:
        material.content_summary = data['content_summary']

    if 'tags' in data:
        material.set_tags(data['tags'])

    db.session.add(material)
    db.session.commit()

    return jsonify({'material': material.to_dict()})


@app.route('/api/kaogong/materials')
@login_required
def get_study_materials():
    """获取学习资料列表"""
    from models import StudyMaterial

    material_type = request.args.get('type')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))

    query = StudyMaterial.query.filter_by(user_id=session['user_id'])

    if material_type:
        query = query.filter_by(material_type=material_type)

    pagination = query.order_by(StudyMaterial.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'materials': [m.to_dict() for m in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@app.route('/api/kaogong/upload', methods=['POST'])
@login_required
def upload_kaogong_file():
    """上传考公相关文件（题目图片、教材等）"""
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400

    file = request.files['file']
    file_type = request.form.get('type', 'image')  # image, pdf, document

    if file.filename == '':
        return jsonify({'error': '文件名为空'}), 400

    upload_rules = {
        'image': {
            'directory': 'images',
            'allowed': ALLOWED_EXTENSIONS,
            'error': '仅支持 png、jpg、jpeg、gif、webp 图片'
        },
        'pdf': {
            'directory': 'pdfs',
            'allowed': {'pdf'},
            'error': 'PDF资料仅支持 pdf 文件'
        },
        'document': {
            'directory': 'docs',
            'allowed': ALLOWED_DOCUMENT_EXTENSIONS - {'pdf'},
            'error': '文档资料仅支持 doc、docx、txt、md 文件'
        }
    }

    if file_type not in upload_rules:
        return jsonify({'error': '不支持的上传类型'}), 400

    rule = upload_rules[file_type]
    if not allowed_file(file.filename, rule['allowed']):
        return jsonify({'error': rule['error']}), 400

    # 保存文件
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_name = f"{timestamp}_{filename}"

    upload_dir = os.path.join(UPLOAD_FOLDER, rule['directory'])
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, save_name)
    file.save(file_path)

    # 返回URL
    url = f"/static/uploads/{rule['directory']}/{save_name}"

    return jsonify({'url': url, 'filename': filename})


@app.route('/api/kaogong/dashboard')
@login_required
def get_kaogong_dashboard():
    """获取考公复盘仪表板数据"""
    from models import (
        XingceQuestion, XingceStatistics, InterviewRecord, StudyMaterial,
        StudyGoal, StudyTask, StudyCheckin
    )

    # 行测统计
    xingce_stats = XingceStatistics.query.filter_by(user_id=session['user_id']).first()
    if not xingce_stats:
        xingce_stats = XingceStatistics(user_id=session['user_id'])

    # 面试统计
    interview_count = InterviewRecord.query.filter_by(user_id=session['user_id']).count()

    # 最近记录
    recent_xingce = XingceQuestion.query.filter_by(
        user_id=session['user_id']
    ).order_by(XingceQuestion.created_at.desc()).limit(5).all()

    recent_interview = InterviewRecord.query.filter_by(
        user_id=session['user_id']
    ).order_by(InterviewRecord.created_at.desc()).limit(5).all()

    # 资料统计
    material_count = StudyMaterial.query.filter_by(user_id=session['user_id']).count()

    # 学习计划
    today = datetime.now().date()
    active_goals = StudyGoal.query.filter_by(
        user_id=session['user_id'],
        status='active'
    ).order_by(StudyGoal.priority.desc(), StudyGoal.end_date.asc()).all()

    today_tasks = StudyTask.query.filter_by(
        user_id=session['user_id'],
        task_date=today
    ).order_by(StudyTask.order_index).all()

    # 打卡信息
    checkin = StudyCheckin.query.filter_by(
        user_id=session['user_id'],
        checkin_date=today
    ).first()

    # 计算连续打卡天数
    streak = calculate_checkin_streak(session['user_id'])

    today_plan = build_kaogong_today_plan(xingce_stats, interview_count, material_count, active_goals, today_tasks)

    return jsonify({
        'xingce_statistics': xingce_stats.to_dict(),
        'interview_count': interview_count,
        'material_count': material_count,
        'recent_xingce': [q.to_dict() for q in recent_xingce],
        'recent_interview': [r.to_dict() for r in recent_interview],
        'active_goals': [g.to_dict() for g in active_goals],
        'today_tasks': [t.to_dict() for t in today_tasks],
        'checkin': checkin.to_dict() if checkin else None,
        'checkin_streak': streak,
        'today_plan': today_plan
    })


# ==================== 学习计划管理 ====================

@app.route('/api/kaogong/goals', methods=['GET'])
@login_required
def get_study_goals():
    """获取学习目标列表"""
    from models import StudyGoal

    goals = StudyGoal.query.filter_by(user_id=session['user_id']).order_by(
        StudyGoal.status.desc(),
        StudyGoal.priority.desc(),
        StudyGoal.end_date.asc()
    ).all()

    return jsonify({'goals': [g.to_dict() for g in goals]})


@app.route('/api/kaogong/goal', methods=['POST'])
@login_required
def create_study_goal():
    """创建学习目标"""
    from models import StudyGoal
    from datetime import date

    data = request.get_json()

    # 解析日期
    start_date = None
    end_date = None
    if data.get('start_date'):
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
    if data.get('end_date'):
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()

    goal = StudyGoal(
        user_id=session['user_id'],
        goal_type=data.get('goal_type', 'comprehensive'),
        title=data.get('title'),
        description=data.get('description'),
        target_value=data.get('target_value'),
        unit=data.get('unit'),
        start_date=start_date,
        end_date=end_date,
        priority=data.get('priority', 'medium')
    )

    db.session.add(goal)
    db.session.commit()

    return jsonify({'goal': goal.to_dict(), 'message': '目标创建成功'})


@app.route('/api/kaogong/goal/<int:goal_id>', methods=['PUT'])
@login_required
def update_study_goal(goal_id):
    """更新学习目标"""
    from models import StudyGoal

    goal = StudyGoal.query.filter_by(id=goal_id, user_id=session['user_id']).first()
    if not goal:
        return jsonify({'error': '目标不存在'}), 404

    data = request.get_json()

    if 'title' in data:
        goal.title = data['title']
    if 'description' in data:
        goal.description = data['description']
    if 'target_value' in data:
        goal.target_value = data['target_value']
    if 'current_value' in data:
        goal.current_value = data['current_value']
    if 'status' in data:
        goal.status = data['status']
        if data['status'] == 'completed' and not goal.completed_at:
            goal.completed_at = datetime.now()
    if 'priority' in data:
        goal.priority = data['priority']
    if 'end_date' in data:
        goal.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()

    db.session.commit()

    return jsonify({'goal': goal.to_dict(), 'message': '目标更新成功'})


@app.route('/api/kaogong/goal/<int:goal_id>', methods=['DELETE'])
@login_required
def delete_study_goal(goal_id):
    """删除学习目标"""
    from models import StudyGoal

    goal = StudyGoal.query.filter_by(id=goal_id, user_id=session['user_id']).first()
    if not goal:
        return jsonify({'error': '目标不存在'}), 404

    db.session.delete(goal)
    db.session.commit()

    return jsonify({'message': '目标删除成功'})


@app.route('/api/kaogong/tasks', methods=['GET'])
@login_required
def get_study_tasks():
    """获取学习任务列表"""
    from models import StudyTask

    # 获取日期范围参数
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = StudyTask.query.filter_by(user_id=session['user_id'])

    if start_date:
        query = query.filter(StudyTask.task_date >= datetime.strptime(start_date, '%Y-%m-%d').date())
    if end_date:
        query = query.filter(StudyTask.task_date <= datetime.strptime(end_date, '%Y-%m-%d').date())

    tasks = query.order_by(StudyTask.task_date.desc(), StudyTask.order_index).all()

    return jsonify({'tasks': [t.to_dict() for t in tasks]})


@app.route('/api/kaogong/task', methods=['POST'])
@login_required
def create_study_task():
    """创建学习任务"""
    from models import StudyTask

    data = request.get_json()
    task_date = datetime.strptime(data['task_date'], '%Y-%m-%d').date()

    task = StudyTask(
        user_id=session['user_id'],
        goal_id=data.get('goal_id'),
        task_type=data.get('task_type', 'practice'),
        title=data.get('title'),
        description=data.get('description'),
        target_count=data.get('target_count', 1),
        task_date=task_date,
        status=data.get('status', 'pending')
    )

    db.session.add(task)
    db.session.commit()

    return jsonify({'task': task.to_dict(), 'message': '任务创建成功'})


@app.route('/api/kaogong/task/<int:task_id>', methods=['PUT'])
@login_required
def update_study_task(task_id):
    """更新学习任务"""
    from models import StudyTask

    task = StudyTask.query.filter_by(id=task_id, user_id=session['user_id']).first()
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    data = request.get_json()

    if 'title' in data:
        task.title = data['title']
    if 'description' in data:
        task.description = data['description']
    if 'target_count' in data:
        task.target_count = data['target_count']
    if 'completed_count' in data:
        task.completed_count = data['completed_count']
        # 自动更新状态
        if task.completed_count >= task.target_count:
            task.status = 'completed'
            task.completed_at = datetime.now()
        elif task.completed_count > 0:
            task.status = 'in_progress'
    if 'status' in data:
        task.status = data['status']
        if data['status'] == 'completed' and not task.completed_at:
            task.completed_at = datetime.now()

    db.session.commit()

    return jsonify({'task': task.to_dict(), 'message': '任务更新成功'})


@app.route('/api/kaogong/task/<int:task_id>', methods=['DELETE'])
@login_required
def delete_study_task(task_id):
    """删除学习任务"""
    from models import StudyTask

    task = StudyTask.query.filter_by(id=task_id, user_id=session['user_id']).first()
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    db.session.delete(task)
    db.session.commit()

    return jsonify({'message': '任务删除成功'})


@app.route('/api/kaogong/checkin', methods=['POST'])
@login_required
def create_checkin():
    """学习打卡"""
    from models import StudyCheckin

    today = datetime.now().date()

    # 检查今天是否已打卡
    existing = StudyCheckin.query.filter_by(
        user_id=session['user_id'],
        checkin_date=today
    ).first()

    if existing:
        # 更新现有打卡
        data = request.get_json()
        existing.study_duration = data.get('study_duration', existing.study_duration)
        existing.tasks_completed = data.get('tasks_completed', existing.tasks_completed)
        existing.xingce_count = data.get('xingce_count', existing.xingce_count)
        existing.interview_count = data.get('interview_count', existing.interview_count)
        existing.mood = data.get('mood', existing.mood)
        existing.summary = data.get('summary', existing.summary)

        db.session.commit()

        return jsonify({
            'checkin': existing.to_dict(),
            'streak': calculate_checkin_streak(session['user_id']),
            'message': '打卡更新成功'
        })

    # 创建新打卡
    data = request.get_json()
    checkin = StudyCheckin(
        user_id=session['user_id'],
        checkin_date=today,
        study_duration=data.get('study_duration', 0),
        tasks_completed=data.get('tasks_completed', 0),
        xingce_count=data.get('xingce_count', 0),
        interview_count=data.get('interview_count', 0),
        mood=data.get('mood'),
        summary=data.get('summary')
    )

    db.session.add(checkin)
    db.session.commit()

    return jsonify({
        'checkin': checkin.to_dict(),
        'streak': calculate_checkin_streak(session['user_id']),
        'message': '打卡成功'
    })


@app.route('/api/kaogong/checkin/history', methods=['GET'])
@login_required
def get_checkin_history():
    """获取打卡历史"""
    from models import StudyCheckin

    # 获取最近30天的打卡记录
    from datetime import timedelta
    start_date = (datetime.now() - timedelta(days=30)).date()

    checkins = StudyCheckin.query.filter_by(
        user_id=session['user_id']
    ).filter(
        StudyCheckin.checkin_date >= start_date
    ).order_by(StudyCheckin.checkin_date.desc()).all()

    # 生成日历数据
    calendar_data = {}
    for c in checkins:
        calendar_data[c.checkin_date.isoformat()] = {
            'mood': c.mood,
            'tasks_completed': c.tasks_completed,
            'study_duration': c.study_duration
        }

    return jsonify({
        'checkins': [c.to_dict() for c in checkins],
        'calendar': calendar_data,
        'streak': calculate_checkin_streak(session['user_id'])
    })


def calculate_checkin_streak(user_id):
    """计算连续打卡天数"""
    from models import StudyCheckin

    today = datetime.now().date()
    streak = 0
    check_date = today

    # 检查今天是否打卡
    today_checkin = StudyCheckin.query.filter_by(
        user_id=user_id,
        checkin_date=today
    ).first()

    if not today_checkin:
        # 今天没打卡，从昨天开始计算
        check_date = today - timedelta(days=1)

    while True:
        checkin = StudyCheckin.query.filter_by(
            user_id=user_id,
            checkin_date=check_date
        ).first()

        if checkin:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    return streak


def build_kaogong_today_plan(xingce_stats, interview_count, material_count, active_goals=None, today_tasks=None):
    """构建今日学习计划建议"""
    def number(value, default=0):
        return default if value is None else value

    # 根据各模块数据生成建议
    xingce_total = number(xingce_stats.total_questions)
    interview_count = number(interview_count)

    # 获取最薄弱的题型
    weakest = None
    lowest_accuracy = 100

    type_map = [
        ('verbal', '言语理解', xingce_stats.verbal_accuracy, xingce_stats.verbal_total),
        ('quantitative', '数量关系', xingce_stats.quantitative_accuracy, xingce_stats.quantitative_total),
        ('reasoning', '判断推理', xingce_stats.reasoning_accuracy, xingce_stats.reasoning_total),
        ('data_analysis', '资料分析', xingce_stats.data_analysis_accuracy, xingce_stats.data_analysis_total),
        ('general', '常识判断', xingce_stats.general_accuracy, xingce_stats.general_total),
    ]

    for key, name, accuracy, total in type_map:
        accuracy = number(accuracy)
        total = number(total)
        if total >= 3 and accuracy < lowest_accuracy:
            lowest_accuracy = accuracy
            weakest = (key, name, accuracy)

    # 检查今日任务
    pending_tasks = [t for t in (today_tasks or []) if t.status in ('pending', 'in_progress')]

    if pending_tasks:
        # 有待完成任务
        task = pending_tasks[0]
        actions = [{'title': t.title, 'detail': t.description or ''} for t in pending_tasks[:3]]
        while len(actions) < 3:
            actions.append({'title': '补充复盘', 'detail': '完成后记录耗时、正确率和下一步'})
        return {
            'focus_type': 'task',
            'focus_name': task.title,
            'reason': f"今日计划中有 {len(pending_tasks)} 项待完成任务",
            'actions': actions
        }
    elif xingce_total < 10:
        # 新用户先建立行测样本，避免空数据时推荐失焦
        return {
            'focus_type': 'verbal',
            'focus_name': '言语理解起步',
            'reason': '当前行测练习样本还少，先用少量题目建立正确率和错因基线',
            'actions': [
                {'title': '录入1道言语理解题', 'detail': '先做片段阅读或逻辑填空，记录答案和正确性'},
                {'title': '记录错因', 'detail': '错题至少写一句原因：审题、知识点、计算或时间压力'},
                {'title': '完成1次短面试开口', 'detail': '用1分钟回答一道自我认知或综合分析题，保持表达手感'}
            ]
        }
    elif weakest and weakest[2] < 70:
        # 有薄弱题型
        return {
            'focus_type': weakest[0],
            'focus_name': f"{weakest[1]}强化",
            'reason': f"目前正确率为 {weakest[2]}%，需要重点突破",
            'actions': [
                {'title': '专项练习', 'detail': f'做10道{weakest[1]}题，总结错因'},
                {'title': '知识点回顾', 'detail': '复习该题型核心知识点和解题技巧'},
                {'title': '复盘1道典型错题', 'detail': '写清题干陷阱、正确思路和下次提醒'}
            ]
        }
    elif interview_count < 5:
        # 面试练习不足
        return {
            'focus_type': 'interview',
            'focus_name': '面试开口练',
            'reason': f"累计练习{interview_count}次，建议保持每日练习",
            'actions': [
                {'title': '面试练习', 'detail': '完成1道结构化面试题目'},
                {'title': '复盘总结', 'detail': '对照评价标准，记录改进点'},
                {'title': '优化表达', 'detail': '把答案压缩成“观点-理由-做法”的清晰结构'}
            ]
        }
    else:
        # 默认建议
        return {
            'focus_type': 'balanced',
            'focus_name': '保持节奏',
            'reason': '继续按计划推进，保持学习状态',
            'actions': [
                {'title': '行测练习', 'detail': '完成各类型题目，保持手感'},
                {'title': '面试练习', 'detail': '开口练习1道面试题'},
                {'title': '日终复盘', 'detail': '记录今日最有效的一件事和一个改进点'}
            ]
        }


# ==================== 用户设置 ====================

@app.route('/api/settings')
@login_required
def get_user_settings():
    """获取用户设置"""
    prefs = UserPreferences.query.filter_by(user_id=session['user_id']).first()
    if not prefs:
        # 创建默认设置
        prefs = UserPreferences(user_id=session['user_id'])
        db.session.add(prefs)
        db.session.commit()

    return jsonify({'settings': prefs.to_dict()})


@app.route('/api/settings', methods=['PUT'])
@login_required
def update_user_settings():
    """更新用户设置"""
    prefs = UserPreferences.query.filter_by(user_id=session['user_id']).first()
    if not prefs:
        prefs = UserPreferences(user_id=session['user_id'])
        db.session.add(prefs)

    data = request.get_json(silent=True) or {}

    # 更新功能开关
    if 'enabled_features' in data:
        prefs.set_enabled_features(data['enabled_features'])

    # 更新界面设置
    if 'theme' in data:
        prefs.theme = data['theme']
    if 'language' in data:
        prefs.language = data['language']

    db.session.commit()

    return jsonify({'settings': prefs.to_dict(), 'message': '设置保存成功'})


@app.route('/api/settings/feature', methods=['POST'])
@login_required
def toggle_feature():
    """切换功能开关"""
    data = request.get_json(silent=True) or {}
    module = data.get('module')
    feature = data.get('feature')
    enabled = data.get('enabled', True)

    if not module or not feature:
        return jsonify({'error': '缺少必要参数'}), 400

    prefs = UserPreferences.query.filter_by(user_id=session['user_id']).first()
    if not prefs:
        prefs = UserPreferences(user_id=session['user_id'])
        db.session.add(prefs)

    prefs.set_feature_enabled(module, feature, enabled)
    db.session.commit()

    return jsonify({
        'settings': prefs.to_dict(),
        'message': f'{"启用" if enabled else "禁用"}成功'
    })


def get_user_preferences(user_id):
    """获取用户偏好设置的辅助函数"""
    prefs = UserPreferences.query.filter_by(user_id=user_id).first()
    if not prefs:
        # 创建默认设置
        prefs = UserPreferences(user_id=user_id)
        db.session.add(prefs)
        db.session.commit()
    return prefs

# ==================== 初始化数据库 ====================

@app.before_request
def create_tables():
    """在第一次请求前创建表"""
    if not hasattr(app, 'tables_created'):
        db.create_all()
        ensure_runtime_schema()
        app.tables_created = True
        # 初始化AI引擎
        init_ai_engine()


# ==================== 主入口 ====================

if __name__ == '__main__':
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
