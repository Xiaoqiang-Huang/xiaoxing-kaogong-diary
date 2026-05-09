"""
小星考公日记启动脚本
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, init_ai_engine
from config import Config
from models import User
from ai_engine import DiaryAnalyzer

diary_analyzer = DiaryAnalyzer()

def init_db():
    """初始化数据库"""
    with app.app_context():
        db.create_all()
        print("✓ 数据库初始化完成")

        # 可选创建默认用户。密码必须来自环境变量，避免把可登录口令写进代码。
        if Config.CREATE_DEFAULT_USER:
            default_username = Config.DEFAULT_USERNAME
            existing_user = User.query.filter_by(username=default_username).first()

            if not existing_user:
                if not Config.DEFAULT_PASSWORD:
                    print("⚠ 已启用默认用户创建，但未设置 DEFAULT_PASSWORD，已跳过")
                else:
                    default_user = User(username=default_username)
                    default_user.set_password(Config.DEFAULT_PASSWORD)
                    db.session.add(default_user)
                    db.session.commit()
                    print(f"✓ 默认用户已创建: {default_username}")
            else:
                print(f"✓ 默认用户已存在: {default_username}")
        else:
            print("✓ 默认用户创建已关闭，可通过 /register 注册账号")

        # 初始化AI引擎（测试连接）
        init_ai_engine()

        # 检查状态
        from app import four_sages_engine
        if four_sages_engine.is_available():
            print(f"✓ AI对话引擎已就绪 ({four_sages_engine.base_url})")
        else:
            print("⚠ AI对话引擎: 模拟模式（请检查API配置）")

        if diary_analyzer.psychoanalyze:
            print("✓ 心理分析模块已加载")
        else:
            print("⚠ 心理分析模块未加载")

def main():
    print("=" * 50)
    print("📔 小星考公日记")
    print("=" * 50)

    # 初始化数据库
    init_db()

    print("\n启动服务...")
    print("本地访问: http://localhost:5000")
    print("按 Ctrl+C 停止服务\n")

    # 启动应用
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)

if __name__ == '__main__':
    main()

