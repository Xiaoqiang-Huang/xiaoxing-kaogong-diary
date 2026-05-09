# 小星考公日记

Xiaoxing Kaogong Diary，一个 Flask 个人日记与考公复盘 Web 应用，包含对话式日记、历史记录、考公复盘、语音转写、日报生成、记忆待办识别和管理员配置入口。

## 安全说明

这个仓库是脱敏后的公开版本

请复制 `.env.example` 为 `.env` 后再填入自己的密钥。

## 许可证

本项目采用 [PolyForm Noncommercial License 1.0.0](LICENSE)。

- 允许个人学习、研究、测试、非商业自用。
- 允许非商业组织按许可证使用。
- 商业使用、公司内部部署、二次开发销售、SaaS 服务化部署等，需要先获得作者书面授权。

Commercial use requires prior written permission from the author.

## 快速开始

### Windows 一键启动

下载后双击：

```text
setup_and_run.bat
```

脚本会自动创建虚拟环境、安装依赖、复制 `.env.example`、生成本地 `SECRET_KEY`，然后启动服务。

打开：

```text
http://127.0.0.1:5000
```

首次使用访问 `/register` 注册账号。

更详细步骤见 [QUICKSTART.md](QUICKSTART.md)。

### 手动启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python start.py
```

默认访问：

- 本地：`http://127.0.0.1:5000`
- 注册：`/register`
- 设置：`/settings`

## AI 配置

在 `.env` 中配置：

```env
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=
SECRET_KEY=replace-with-a-random-secret
```

管理员也可以在设置页的“内置 AI API”区域修改 Base URL 和 API Key，保存后会热重载。

## 语音转写

项目支持 OpenAI 兼容的 `/audio/transcriptions` 接口。可以接 OpenAI，也可以接本地 `faster-whisper-server`：

```powershell
docker compose -f docker-compose.faster-whisper.yml up -d
```

`.env` 示例：

```env
SPEECH_TO_TEXT_PROVIDER=openai
OPENAI_API_KEY=local-key-can-be-any-non-empty-value
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_TRANSCRIBE_MODEL=Systran/faster-whisper-small
```

## 运行测试

```powershell
python -m unittest discover tests -v
```

## 发布前检查

```powershell
git status --short
git ls-files
```

确认不要提交 `.env`、`data/`、`static/uploads/`、日志和缓存。


