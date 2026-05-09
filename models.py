"""
数据库模型定义
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import copy
import json
from enum import Enum
from interview_standards import EXTRA_INTERVIEW_QUESTIONS

db = SQLAlchemy()

class User(db.Model):
    """用户表"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    chat_background = db.Column(db.String(255), nullable=True)  # 对话背景图片URL
    background_color = db.Column(db.String(20), nullable=True)  # 纯色背景（如 #F5EFE4）
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 关系
    diaries = db.relationship('Diary', backref='user', lazy=True, cascade='all, delete-orphan')
    preferences = db.relationship('UserPreferences', backref='user', uselist=False, cascade='all, delete-orphan')

    def set_password(self, password):
        """设置密码"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """验证密码"""
        return check_password_hash(self.password_hash, password)

    def get_display_name(self):
        """Return the preferred name shown in greetings."""
        return (self.display_name or self.username or "用户").strip()

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'display_name': self.get_display_name(),
            'is_admin': self.is_admin,
            'created_at': self.created_at.isoformat()
        }


class UserPreferences(db.Model):
    """用户偏好设置"""
    __tablename__ = 'user_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)

    # 功能开关（JSON存储）
    enabled_features = db.Column(db.Text, nullable=False)  # JSON格式的功能开关配置

    # 界面设置
    theme = db.Column(db.String(20), default='light')  # light, dark
    language = db.Column(db.String(10), default='zh-CN')

    # 时间戳
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # 默认功能配置
    DEFAULT_FEATURES = {
        # 考公模块
        'kaogong': {
            'enabled': True,
            'modules': {
                'xingce': True,      # 行测复盘
                'interview': True,   # 面试复盘
                'materials': True,   # 学习资料
                'plan': True,        # 学习计划
                'checkin': True,     # 每日打卡
            }
        },
        # 日记模块
        'diary': {
            'enabled': True,
            'features': {
                'voice_input': True,     # 语音输入
                'ai_analysis': True,     # AI分析
                'four_sages': True,      # 四圣谏言
                'export': True,          # 导出功能
                'daily_report': True,    # 每日日报
                'ai_memory_extract': True,   # 使用AI识别历史记忆（可能发送日记片段）
            }
        },
        # 通知设置
        'notifications': {
            'daily_reminder': True,      # 每日提醒
            'reminder_time': '08:00',    # 提醒时间
            'streak_reminder': True,     # 连续打卡提醒
        }
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.enabled_features:
            self.set_enabled_features(self.default_features())

    @classmethod
    def default_features(cls):
        """Return an isolated copy so callers cannot mutate the class default."""
        return copy.deepcopy(cls.DEFAULT_FEATURES)

    def set_enabled_features(self, features_dict):
        """设置功能配置"""
        self.enabled_features = json.dumps(features_dict, ensure_ascii=False)

    def get_enabled_features(self):
        """获取功能配置"""
        try:
            saved = json.loads(self.enabled_features) if self.enabled_features else {}
        except:
            saved = {}

        features = self.default_features()

        def deep_merge(base, override):
            for key, value in (override or {}).items():
                if isinstance(value, dict) and isinstance(base.get(key), dict):
                    deep_merge(base[key], value)
                else:
                    base[key] = value

        deep_merge(features, saved)
        return features

    def is_feature_enabled(self, module, feature=None):
        """检查功能是否启用"""
        features = self.get_enabled_features()
        if module not in features:
            return True  # 默认启用

        if feature is None:
            return features[module].get('enabled', True)

        module_config = features[module]
        if module == 'kaogong' and feature in module_config.get('modules', {}):
            return module_config['modules'][feature]
        elif module == 'diary' and feature in module_config.get('features', {}):
            return module_config['features'][feature]

        return True

    def set_feature_enabled(self, module, feature, enabled):
        """设置功能开关"""
        features = self.get_enabled_features()
        if module not in features:
            features[module] = {}

        if module == 'kaogong':
            if 'modules' not in features[module]:
                features[module]['modules'] = {}
            features[module]['modules'][feature] = enabled
        elif module == 'diary':
            if 'features' not in features[module]:
                features[module]['features'] = {}
            features[module]['features'][feature] = enabled
        else:
            features[module][feature] = enabled

        self.set_enabled_features(features)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'enabled_features': self.get_enabled_features(),
            'theme': self.theme,
            'language': self.language,
            'updated_at': self.updated_at.isoformat()
        }


class Diary(db.Model):
    """日记表"""
    __tablename__ = 'diaries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.String(10), nullable=False, index=True)  # YYYY-MM-DD
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # 关系
    analysis = db.relationship('Analysis', backref='diary', uselist=False, cascade='all, delete-orphan')

    def to_dict(self, include_analysis=False):
        result = {
            'id': self.id,
            'date': self.date,
            'content': self.content,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
        if include_analysis and self.analysis:
            result['analysis'] = self.analysis.to_dict()
        return result


class Analysis(db.Model):
    """分析结果表"""
    __tablename__ = 'analyses'

    id = db.Column(db.Integer, primary_key=True)
    diary_id = db.Column(db.Integer, db.ForeignKey('diaries.id'), nullable=False)

    # 情绪分析
    emotion = db.Column(db.String(20))
    emotion_score = db.Column(db.Float)

    # 关键词
    keywords = db.Column(db.Text)  # JSON存储

    # 四圣谏言
    four_sages = db.Column(db.Text)  # JSON存储

    # 写作建议
    suggestions = db.Column(db.Text)

    # 完整分析JSON
    full_analysis = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_keywords(self, keywords_list):
        self.keywords = json.dumps(keywords_list, ensure_ascii=False)

    def get_keywords(self):
        return json.loads(self.keywords) if self.keywords else []

    def set_four_sages(self, four_sages_dict):
        self.four_sages = json.dumps(four_sages_dict, ensure_ascii=False)

    def get_four_sages(self):
        return json.loads(self.four_sages) if self.four_sages else {}

    def set_full_analysis(self, analysis_dict):
        self.full_analysis = json.dumps(analysis_dict, ensure_ascii=False)

    def get_full_analysis(self):
        return json.loads(self.full_analysis) if self.full_analysis else {}

    def to_dict(self):
        return {
            'id': self.id,
            'emotion': self.emotion,
            'emotion_score': self.emotion_score,
            'keywords': self.get_keywords(),
            'four_sages': self.get_four_sages(),
            'suggestions': self.suggestions,
            'created_at': self.created_at.isoformat()
        }


class Conversation(db.Model):
    """对话历史表（用于AI对话模式）"""
    __tablename__ = 'conversations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content,
            'created_at': self.created_at.isoformat()
        }


class MemoryItem(db.Model):
    """长期记忆条目，用于追踪待办、承诺和用户偏好。"""
    __tablename__ = 'memory_items'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    item_type = db.Column(db.String(30), default='todo', nullable=False, index=True)
    status = db.Column(db.String(20), default='open', nullable=False, index=True)
    title = db.Column(db.String(220), nullable=False)
    content = db.Column(db.Text)
    due_date = db.Column(db.String(10), index=True)
    source = db.Column(db.String(80), default='diary_chat')
    source_date = db.Column(db.String(10), index=True)
    item_metadata = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def set_metadata(self, metadata):
        self.item_metadata = json.dumps(metadata or {}, ensure_ascii=False)

    def get_metadata(self):
        try:
            return json.loads(self.item_metadata) if self.item_metadata else {}
        except Exception:
            return {}

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'item_type': self.item_type,
            'status': self.status,
            'title': self.title,
            'content': self.content,
            'due_date': self.due_date,
            'source': self.source,
            'source_date': self.source_date,
            'metadata': self.get_metadata(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ReportConfig(db.Model):
    """日报推送配置"""
    __tablename__ = 'report_configs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # 自定义话题
    topics = db.Column(db.Text)  # JSON存储话题列表
    custom_topics = db.Column(db.Text)  # JSON存储自定义话题列表
    use_default = db.Column(db.Boolean, default=True)  # 是否使用默认话题

    # 推送时间
    push_time = db.Column(db.String(5), default='08:00')  # HH:MM格式
    timezone = db.Column(db.String(50), default='Asia/Shanghai')

    # 是否启用
    enabled = db.Column(db.Boolean, default=True)

    # 最近一次推送时间
    last_pushed_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def set_topics(self, topics_list):
        self.topics = json.dumps(topics_list, ensure_ascii=False)

    def get_topics(self):
        return json.loads(self.topics) if self.topics else self._default_topics()

    def set_custom_topics(self, topics_list):
        self.custom_topics = json.dumps(topics_list, ensure_ascii=False)

    def get_custom_topics(self):
        return json.loads(self.custom_topics) if self.custom_topics else []

    def _default_topics(self):
        return [
            "官方时政与政策资讯",
            "考公申论素材与面试表达",
            "AI热点与工具动态",
            "今日天气与提醒",
            "个人成长建议",
            "健康生活提示"
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'topics': self.get_topics(),
            'custom_topics': self.get_custom_topics(),
            'push_time': self.push_time,
            'timezone': self.timezone,
            'enabled': self.enabled,
            'last_pushed_at': self.last_pushed_at.isoformat() if self.last_pushed_at else None,
            'created_at': self.created_at.isoformat()
        }


class DailyReport(db.Model):
    """日报推送记录"""
    __tablename__ = 'daily_reports'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    report_date = db.Column(db.String(10), nullable=False, index=True)  # YYYY-MM-DD

    # 报告内容
    content = db.Column(db.Text)  # Markdown格式的报告
    summary = db.Column(db.Text)  # 简要摘要

    # 引用的日记ID
    diary_ids = db.Column(db.Text)  # JSON存储

    # 外部信息来源（用于交叉验证）
    sources = db.Column(db.Text)  # JSON存储来源信息

    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_diary_ids(self, ids_list):
        self.diary_ids = json.dumps(ids_list, ensure_ascii=False)

    def get_diary_ids(self):
        return json.loads(self.diary_ids) if self.diary_ids else []

    def set_sources(self, sources_list):
        self.sources = json.dumps(sources_list, ensure_ascii=False)

    def get_sources(self):
        return json.loads(self.sources) if self.sources else []

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'report_date': self.report_date,
            'content': self.content,
            'summary': self.summary,
            'diary_ids': self.get_diary_ids(),
            'sources': self.get_sources(),
            'created_at': self.created_at.isoformat()
        }


# ==================== 考公复盘系统模型 ====================

class StudyGoal(db.Model):
    """学习目标"""
    __tablename__ = 'study_goals'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # 目标信息
    goal_type = db.Column(db.String(20), nullable=False)  # xingce, interview, comprehensive
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # 目标设定
    target_value = db.Column(db.Integer)  # 目标值（如：70分、30题）
    current_value = db.Column(db.Integer, default=0)  # 当前进度
    unit = db.Column(db.String(20))  # 单位（分、题、小时）

    # 时间范围
    start_date = db.Column(db.Date)  # 开始日期
    end_date = db.Column(db.Date)  # 目标完成日期

    # 状态
    status = db.Column(db.String(20), default='active')  # active, completed, paused, cancelled
    priority = db.Column(db.String(20), default='medium')  # high, medium, low

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at = db.Column(db.DateTime)

    @property
    def progress_percent(self):
        """进度百分比"""
        if self.target_value and self.target_value > 0:
            return min(100, round((self.current_value or 0) / self.target_value * 100, 1))
        return 0

    @property
    def days_remaining(self):
        """剩余天数"""
        if not self.end_date or self.status == 'completed':
            return 0
        delta = self.end_date - datetime.now().date()
        return max(0, delta.days)

    @property
    def is_overdue(self):
        """是否逾期"""
        if not self.end_date or self.status == 'completed':
            return False
        return datetime.now().date() > self.end_date

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'goal_type': self.goal_type,
            'title': self.title,
            'description': self.description,
            'target_value': self.target_value,
            'current_value': self.current_value or 0,
            'unit': self.unit,
            'progress_percent': self.progress_percent,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'days_remaining': self.days_remaining,
            'status': self.status,
            'priority': self.priority,
            'is_overdue': self.is_overdue,
            'created_at': self.created_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }


class StudyTask(db.Model):
    """每日学习任务"""
    __tablename__ = 'study_tasks'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    goal_id = db.Column(db.Integer, db.ForeignKey('study_goals.id'), nullable=True)  # 关联目标

    # 任务信息
    task_type = db.Column(db.String(20), nullable=False)  # xingce, interview, reading, practice
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # 任务设定
    target_count = db.Column(db.Integer, default=1)  # 目标数量（如：做5题）
    completed_count = db.Column(db.Integer, default=0)  # 已完成数量

    # 排期
    task_date = db.Column(db.Date, nullable=False, index=True)  # 任务日期
    order_index = db.Column(db.Integer, default=0)  # 排序索引

    # 状态
    status = db.Column(db.String(20), default='pending')  # pending, in_progress, completed, skipped

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.now)
    completed_at = db.Column(db.DateTime)

    @property
    def progress_percent(self):
        """进度百分比"""
        if self.target_count and self.target_count > 0:
            return min(100, round((self.completed_count or 0) / self.target_count * 100, 1))
        return 100 if self.status == 'completed' else 0

    @property
    def is_today(self):
        """是否今天"""
        return self.task_date == datetime.now().date()

    @property
    def is_overdue(self):
        """是否逾期"""
        return self.task_date < datetime.now().date() and self.status != 'completed'

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'goal_id': self.goal_id,
            'task_type': self.task_type,
            'title': self.title,
            'description': self.description,
            'target_count': self.target_count,
            'completed_count': self.completed_count or 0,
            'progress_percent': self.progress_percent,
            'task_date': self.task_date.isoformat(),
            'status': self.status,
            'is_today': self.is_today,
            'is_overdue': self.is_overdue,
            'created_at': self.created_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }


class StudyCheckin(db.Model):
    """学习打卡记录"""
    __tablename__ = 'study_checkins'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # 打卡信息
    checkin_date = db.Column(db.Date, nullable=False, unique=True, index=True)  # 打卡日期
    study_duration = db.Column(db.Integer, default=0)  # 学习时长（分钟）
    tasks_completed = db.Column(db.Integer, default=0)  # 完成任务数
    xingce_count = db.Column(db.Integer, default=0)  # 行测题数
    interview_count = db.Column(db.Integer, default=0)  # 面试练习数

    # 心情和总结
    mood = db.Column(db.String(20))  # happy, normal, tired, stressed
    summary = db.Column(db.Text)  # 今日总结

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.now)

    @property
    def streak_day(self):
        """连续打卡天数（需要额外计算）"""
        return 0

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'checkin_date': self.checkin_date.isoformat(),
            'study_duration': self.study_duration,
            'tasks_completed': self.tasks_completed,
            'xingce_count': self.xingce_count,
            'interview_count': self.interview_count,
            'mood': self.mood,
            'summary': self.summary,
            'created_at': self.created_at.isoformat()
        }


class XingceQuestion(db.Model):
    """行测题目记录"""
    __tablename__ = 'xingce_questions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # 题目信息
    question_type = db.Column(db.String(20), nullable=False)  # verbal, quantitative, reasoning, data_analysis, general
    content = db.Column(db.Text, nullable=False)  # 题目内容
    options = db.Column(db.Text)  # JSON存储选项列表
    correct_answer = db.Column(db.String(10))  # 正确答案

    # 用户答题
    user_answer = db.Column(db.String(10))  # 用户答案
    is_correct = db.Column(db.Boolean)  # 是否正确
    time_spent = db.Column(db.Integer)  # 用时(秒)

    # 解析和标签
    analysis = db.Column(db.Text)  # 题目解析
    source = db.Column(db.String(100))  # 来源
    tags = db.Column(db.Text)  # JSON存储标签
    image_url = db.Column(db.String(255))  # 题目图片URL

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.now)
    reviewed_at = db.Column(db.DateTime)  # 复习时间

    def set_options(self, options_list):
        self.options = json.dumps(options_list, ensure_ascii=False)

    def get_options(self):
        return json.loads(self.options) if self.options else []

    def set_tags(self, tags_list):
        self.tags = json.dumps(tags_list, ensure_ascii=False)

    def get_tags(self):
        return json.loads(self.tags) if self.tags else []

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'question_type': self.question_type,
            'content': self.content,
            'options': self.get_options(),
            'correct_answer': self.correct_answer,
            'user_answer': self.user_answer,
            'is_correct': self.is_correct,
            'time_spent': self.time_spent,
            'analysis': self.analysis,
            'source': self.source,
            'tags': self.get_tags(),
            'image_url': self.image_url,
            'created_at': self.created_at.isoformat(),
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None
        }


class InterviewRecord(db.Model):
    """面试复盘记录"""
    __tablename__ = 'interview_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # 面试信息
    interview_type = db.Column(db.String(20), nullable=False)  # structured, half_structured, no_structured, pressure
    category = db.Column(db.String(20), nullable=False)  # self_intro, situation, comprehensive, emergency, interpersonal, organization, vocational

    # 题目和回答
    question = db.Column(db.Text, nullable=False)  # 面试题目
    answer_text = db.Column(db.Text, nullable=False)  # 回答文字
    audio_url = db.Column(db.String(255))  # 语音录音URL
    duration = db.Column(db.Integer)  # 回答时长(秒)

    # 评价
    ai_evaluation = db.Column(db.Text)  # JSON存储AI评价
    self_reflection = db.Column(db.Text)  # 自我反思

    # 标签和时间
    tags = db.Column(db.Text)  # JSON存储标签
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def set_ai_evaluation(self, evaluation_dict):
        self.ai_evaluation = json.dumps(evaluation_dict, ensure_ascii=False)

    def get_ai_evaluation(self):
        return json.loads(self.ai_evaluation) if self.ai_evaluation else {}

    def set_tags(self, tags_list):
        self.tags = json.dumps(tags_list, ensure_ascii=False)

    def get_tags(self):
        return json.loads(self.tags) if self.tags else []

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'interview_type': self.interview_type,
            'category': self.category,
            'question': self.question,
            'answer_text': self.answer_text,
            'audio_url': self.audio_url,
            'duration': self.duration,
            'ai_evaluation': self.get_ai_evaluation(),
            'self_reflection': self.self_reflection,
            'tags': self.get_tags(),
            'created_at': self.created_at.isoformat()
        }


class StudyMaterial(db.Model):
    """学习资料库"""
    __tablename__ = 'study_materials'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # 资料信息
    title = db.Column(db.String(200), nullable=False)
    material_type = db.Column(db.String(20), nullable=False)  # xingce, interview, general
    file_url = db.Column(db.String(255), nullable=False)  # 文件URL
    file_type = db.Column(db.String(10), nullable=False)  # pdf, doc, txt

    # 解析内容
    content_summary = db.Column(db.Text)  # 内容摘要
    extracted_knowledge = db.Column(db.Text)  # JSON存储提取的知识点

    # 标签和时间
    tags = db.Column(db.Text)  # JSON存储标签
    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_extracted_knowledge(self, knowledge_list):
        self.extracted_knowledge = json.dumps(knowledge_list, ensure_ascii=False)

    def get_extracted_knowledge(self):
        return json.loads(self.extracted_knowledge) if self.extracted_knowledge else []

    def set_tags(self, tags_list):
        self.tags = json.dumps(tags_list, ensure_ascii=False)

    def get_tags(self):
        return json.loads(self.tags) if self.tags else []

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'material_type': self.material_type,
            'file_url': self.file_url,
            'file_type': self.file_type,
            'content_summary': self.content_summary,
            'extracted_knowledge': self.get_extracted_knowledge(),
            'tags': self.get_tags(),
            'created_at': self.created_at.isoformat()
        }


class XingceStatistics(db.Model):
    """行测统计数据"""
    __tablename__ = 'xingce_statistics'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)

    # 各题型的统计
    verbal_total = db.Column(db.Integer, default=0)  # 言语理解总数
    verbal_correct = db.Column(db.Integer, default=0)  # 言语理解正确数

    quantitative_total = db.Column(db.Integer, default=0)  # 数量关系总数
    quantitative_correct = db.Column(db.Integer, default=0)  # 数量关系正确数

    reasoning_total = db.Column(db.Integer, default=0)  # 判断推理总数
    reasoning_correct = db.Column(db.Integer, default=0)  # 判断推理正确数

    data_analysis_total = db.Column(db.Integer, default=0)  # 资料分析总数
    data_analysis_correct = db.Column(db.Integer, default=0)  # 资料分析正确数

    general_total = db.Column(db.Integer, default=0)  # 常识判断总数
    general_correct = db.Column(db.Integer, default=0)  # 常识判断正确数

    # 总计
    total_questions = db.Column(db.Integer, default=0)
    total_correct = db.Column(db.Integer, default=0)

    # 时间戳
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def overall_accuracy(self):
        """总体正确率"""
        total = self.total_questions or 0
        correct = self.total_correct or 0
        if total == 0:
            return 0
        return round(correct / total * 100, 2)

    @property
    def verbal_accuracy(self):
        """言语理解正确率"""
        total = self.verbal_total or 0
        correct = self.verbal_correct or 0
        if total == 0:
            return 0
        return round(correct / total * 100, 2)

    @property
    def quantitative_accuracy(self):
        """数量关系正确率"""
        total = self.quantitative_total or 0
        correct = self.quantitative_correct or 0
        if total == 0:
            return 0
        return round(correct / total * 100, 2)

    @property
    def reasoning_accuracy(self):
        """判断推理正确率"""
        total = self.reasoning_total or 0
        correct = self.reasoning_correct or 0
        if total == 0:
            return 0
        return round(correct / total * 100, 2)

    @property
    def data_analysis_accuracy(self):
        """资料分析正确率"""
        total = self.data_analysis_total or 0
        correct = self.data_analysis_correct or 0
        if total == 0:
            return 0
        return round(correct / total * 100, 2)

    @property
    def general_accuracy(self):
        """常识判断正确率"""
        total = self.general_total or 0
        correct = self.general_correct or 0
        if total == 0:
            return 0
        return round(correct / total * 100, 2)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'verbal': {'total': self.verbal_total or 0, 'correct': self.verbal_correct or 0, 'accuracy': self.verbal_accuracy},
            'quantitative': {'total': self.quantitative_total or 0, 'correct': self.quantitative_correct or 0, 'accuracy': self.quantitative_accuracy},
            'reasoning': {'total': self.reasoning_total or 0, 'correct': self.reasoning_correct or 0, 'accuracy': self.reasoning_accuracy},
            'data_analysis': {'total': self.data_analysis_total or 0, 'correct': self.data_analysis_correct or 0, 'accuracy': self.data_analysis_accuracy},
            'general': {'total': self.general_total or 0, 'correct': self.general_correct or 0, 'accuracy': self.general_accuracy},
            'overall': {'total': self.total_questions or 0, 'correct': self.total_correct or 0, 'accuracy': self.overall_accuracy},
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ==================== 预设面试题目库 ====================

DEFAULT_INTERVIEW_QUESTIONS = [
    {
        "id": "int_001",
        "category": "self_intro",
        "question": "请做一个简单的自我介绍。",
        "reference_answer": "应包含：基本信息、教育背景、工作/实践经历、个人特质、与岗位的匹配度。控制在2-3分钟。",
        "evaluation_criteria": {
            "逻辑性": "介绍是否有清晰的结构",
            "针对性": "是否突出与岗位匹配的特质",
            "时间控制": "是否控制在合理时间",
            "表达流畅": "语言是否流畅自然"
        },
        "tags": ["基础", "必考"]
    },
    {
        "id": "int_002",
        "category": "comprehensive",
        "question": "有人说'考上公务员就进了保险箱，一辈子不用愁了'。对此你怎么看？",
        "reference_answer": "应从：1)分析观点背后的社会认知 2)阐述公务员工作的性质和责任 3)表达正确的职业观和价值观。",
        "evaluation_criteria": {
            "观点明确": "是否表明清晰立场",
            "分析深度": "是否有深层次分析",
            "价值观正确": "是否符合公务员价值观",
            "条理清晰": "论述是否有条理"
        },
        "tags": ["综合分析", "价值观"]
    },
    {
        "id": "int_003",
        "category": "emergency",
        "question": "如果你是窗口工作人员，有一位群众因办事没办成，情绪激动地在办事大厅大吵大闹，引来群众围观，你会怎么办？",
        "reference_answer": "应：1)迅速控制局面 2)耐心倾听诉求 3)依法依规处理 4)后续反思改进。",
        "evaluation_criteria": {
            "应急能力": "是否能迅速反应",
            "沟通技巧": "是否能有效沟通",
            "依法依规": "处理是否符合规定",
            "服务意识": "是否体现服务理念"
        },
        "tags": ["应急应变", "实务"]
    },
    {
        "id": "int_004",
        "category": "interpersonal",
        "question": "你刚入职，领导让你和一个有矛盾的同事合作完成一项工作，你该怎么办？",
        "reference_answer": "应：1)正确认识同事关系 2)主动沟通化解矛盾 3)以工作为重 4)事后总结反思。",
        "evaluation_criteria": {
            "大局意识": "是否能以工作为重",
            "沟通能力": "如何处理关系",
            "工作态度": "是否积极主动",
            "处理方式": "方式是否得当"
        },
        "tags": ["人际关系", "职场"]
    },
    {
        "id": "int_005",
        "category": "organization",
        "question": "领导让你组织一次单位内部的业务培训，你打算怎么组织？",
        "reference_answer": "应包含：1)培训需求调研 2)制定培训方案 3)协调资源 4)组织实施 5)总结评估。",
        "evaluation_criteria": {
            "计划性": "是否有完整计划",
            "可行性": "方案是否可行",
            "细节考虑": "是否考虑细节",
            "创新性": "是否有创新点"
        },
        "tags": ["组织协调", "实务"]
    },
    {
        "id": "int_006",
        "category": "vocational",
        "question": "你报考的这个岗位，你认为需要具备哪些素质？你有哪些优势和不足？",
        "reference_answer": "应：1)准确把握岗位要求 2)客观分析自身优势 3)坦诚面对不足 4)提出改进计划。",
        "evaluation_criteria": {
            "岗位认知": "是否准确把握岗位",
            "自我认知": "是否客观认识自己",
            "匹配度": "人岗匹配分析",
            "改进意识": "是否有改进意识"
        },
        "tags": ["职位认知", "自我分析"]
    },
    {
        "id": "int_007",
        "category": "situation",
        "question": "如果你被录用，但被分配到一个偏远地区的基层岗位，你会接受吗？",
        "reference_answer": "应：1)表明服从分配的态度 2)分析基层工作的价值 3)表达适应和成长的决心。",
        "evaluation_criteria": {
            "态度立场": "是否明确表态",
            "认知深度": "对基层工作的理解",
            "适应能力": "是否能适应环境",
            "成长思维": "是否有成长规划"
        },
        "tags": ["情景模拟", "基层"]
    },
    {
        "id": "int_008",
        "category": "comprehensive",
        "question": "当前，有些地方政府为了追求政绩，搞'形象工程''面子工程'。对此你怎么看？",
        "reference_answer": "应从：1)指出问题的危害 2)分析问题根源 3)提出解决对策 4)作为公务员应如何做。",
        "evaluation_criteria": {
            "问题认识": "是否认识问题本质",
            "分析深度": "分析是否深入",
            "对策可行": "对策是否可行",
            "价值导向": "价值观是否正确"
        },
        "tags": ["综合分析", "社会热点"]
    },
    {
        "id": "int_009",
        "category": "emergency",
        "question": "在一次重要的会议上，你正在发言，突然有人打断并质疑你的观点，气氛很尴尬，你怎么办？",
        "reference_answer": "应：1)保持冷静 2)礼貌回应 3)妥善处理 4)继续发言。",
        "evaluation_criteria": {
            "应变能力": "反应是否迅速得体",
            "情绪控制": "是否保持冷静",
            "沟通技巧": "回应是否恰当",
            "专业素养": "是否展现专业"
        },
        "tags": ["应急应变", "会议"]
    },
    {
        "id": "int_010",
        "category": "interpersonal",
        "question": "你的领导经常在下班前给你安排紧急任务，影响你的个人安排，你怎么办？",
        "reference_answer": "应：1)正确认识 2)高效完成 3)适时沟通 4)做好规划。",
        "evaluation_criteria": {
            "态度端正": "态度是否正确",
            "执行能力": "能否完成任务",
            "沟通方式": "沟通是否得当",
            "自我管理": "是否有规划"
        },
        "tags": ["人际关系", "工作压力"]
    }
]

DEFAULT_INTERVIEW_QUESTIONS.extend(EXTRA_INTERVIEW_QUESTIONS)

# 面试分类名称映射
INTERVIEW_CATEGORY_NAMES = {
    "self_intro": "自我介绍",
    "situation": "情景模拟",
    "comprehensive": "综合分析",
    "emergency": "应急应变",
    "interpersonal": "人际关系",
    "organization": "组织协调",
    "vocational": "职位认知",
    "leaderless_group": "无领导小组",
    "professional": "专业专项"
}

# 面试类型名称映射
INTERVIEW_TYPE_NAMES = {
    "structured": "结构化面试",
    "half_structured": "半结构化面试",
    "leaderless_group": "无领导小组讨论",
    "pressure": "压力面试"
}

# 行测题目类型名称映射
XINGCE_TYPE_NAMES = {
    "verbal": "言语理解",
    "quantitative": "数量关系",
    "reasoning": "判断推理",
    "data_analysis": "资料分析",
    "general": "常识判断"
}
