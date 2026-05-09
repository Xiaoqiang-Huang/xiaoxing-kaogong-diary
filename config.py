"""
小星考公日记配置文件
"""
import os
import secrets

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _get_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _get_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default

class Config:
    """基础配置"""
    APP_ENV = os.environ.get('APP_ENV', os.environ.get('FLASK_ENV', 'development')).lower()
    DEBUG = _get_bool('FLASK_DEBUG', APP_ENV != 'production')
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = _get_int('PORT', 5000)

    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY') or (
        f"dev-only-{secrets.token_urlsafe(32)}" if DEBUG else None
    )
    if not SECRET_KEY:
        raise RuntimeError('生产环境必须设置 SECRET_KEY 环境变量')

    # 数据库配置
    DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'diary.db')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'sqlite:///{DATABASE_PATH}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Claude API配置：只从环境变量或 .env 读取，避免把密钥写进代码仓库
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    ANTHROPIC_BASE_URL = os.environ.get('ANTHROPIC_BASE_URL', '').strip()

    # 可选：服务器端语音转文字。浏览器 Web Speech 不稳定时使用。
    SPEECH_TO_TEXT_PROVIDER = os.environ.get('SPEECH_TO_TEXT_PROVIDER', '').strip().lower()
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '').strip()
    OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').strip().rstrip('/')
    OPENAI_TRANSCRIBE_MODEL = os.environ.get('OPENAI_TRANSCRIBE_MODEL', 'gpt-4o-mini-transcribe').strip()

    # 日记存储路径（与现有系统兼容）
    DIARY_MD_PATH = os.path.join(os.path.dirname(BASE_DIR), '日记2026', 'daily')

    # 会话配置
    SESSION_COOKIE_NAME = 'diary_session'
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7  # 7天
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = _get_bool('SESSION_COOKIE_SECURE', APP_ENV == 'production')

    # 公网访问安全开关。开启后默认关闭公开注册，并建议使用 HTTPS 安全 Cookie。
    PUBLIC_ACCESS = _get_bool('PUBLIC_ACCESS', False)
    ALLOW_PUBLIC_REGISTRATION = _get_bool('ALLOW_PUBLIC_REGISTRATION', not PUBLIC_ACCESS)
    REGISTRATION_INVITE_CODE = os.environ.get('REGISTRATION_INVITE_CODE', '').strip()
    LOGIN_MAX_ATTEMPTS = _get_int('LOGIN_MAX_ATTEMPTS', 8)
    LOGIN_RATE_LIMIT_SECONDS = _get_int('LOGIN_RATE_LIMIT_SECONDS', 300)
    REGISTER_MAX_ATTEMPTS = _get_int('REGISTER_MAX_ATTEMPTS', 6)
    REGISTER_RATE_LIMIT_SECONDS = _get_int('REGISTER_RATE_LIMIT_SECONDS', 600)

    # 上传配置
    MAX_CONTENT_LENGTH = _get_int('MAX_CONTENT_LENGTH_MB', 24) * 1024 * 1024
    ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'md'}
    ALLOWED_AUDIO_EXTENSIONS = {'webm', 'wav', 'mp3', 'm4a', 'ogg', 'mp4'}

    # 数据目录
    DATA_PATH = os.path.join(BASE_DIR, 'data')

    # 每页显示数量
    DIARIES_PER_PAGE = 20

    # 可选默认用户。生产环境不要启用；本地可在 .env 中显式配置。
    CREATE_DEFAULT_USER = _get_bool('CREATE_DEFAULT_USER', False)
    DEFAULT_USERNAME = os.environ.get('DEFAULT_USERNAME', 'hxq')
    DEFAULT_PASSWORD = os.environ.get('DEFAULT_PASSWORD', '')

