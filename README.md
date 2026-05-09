# 小星考公日记

Xiaoxing Kaogong Diary，一个 Flask 个人日记与考公复盘 Web 应用，包含对话式日记、历史记录、考公复盘、语音转写、日报生成、记忆待办识别和管理员配置入口。

## 核心功能

### ? 对话式日记记录

- **自然对话**：像和好友聊天一样记录日记，AI 自动整理成结构化日记
- **四圣谏言**：集成曾国藩、芒格、巴菲特、Karpathy 四位智者的思维框架，提供深度省察视角
- **情绪追踪**：自动识别情绪关键词，生成可视化情绪曲线
- **日报生成**：自动汇总当日日记，生成结构化日报
- **记忆待办**：从对话中智能识别待办事项，一键标记完成

### ? 面试复盘系统

- **行测题库管理**：支持言语、判断、数量、资料分析等题型，错题自动统计分析
- **结构化面试练习**：
  - 综合分析能力
  - 言语表达能力
  - 应变能力
  - 计划组织协调能力
  - 人际交往意识与技巧
  - 专业能力
  - 举止仪表
- **AI 面试评价**：根据作答内容，自动评分并提供针对性改进建议
- **进步趋势分析**：可视化展示练习进步曲线

## 快速开始

### Windows 一键启动

1. 安装 [Python 3.11+](https://www.python.org/downloads/)
2. 双击 `setup_and_run.bat`
3. 浏览器打开 `http://127.0.0.1:5000`
4. 访问 `/register` 注册账号
   > **第一个注册的用户自动成为管理员**，可以在 `/settings` 中配置 AI API

脚本会自动：
- 创建虚拟环境 `.venv`
- 安装依赖
- 复制 `.env.example` 为 `.env`
- 生成本地 `SECRET_KEY`
- 启动服务

### 手动启动

```powershell
# Windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python start.py
```

```bash
# Linux/macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python start.py
```

## 使用指南

### 记录日记

1. 登录后进入首页
2. 在输入框中输入今天想记录的内容
3. 点击发送，AI 会以「四圣谏言」框架回复并提供深度分析
4. 对话内容自动保存为日记

### 面试复盘

**面试练习流程**：

1. 进入「考公复盘」页面
2. 选择「结构化面试练习」
3. 系统随机出题（支持选择题型：综合分析、应变能力、人际关系等）
4. **作答方式**：
   - **方式一（推荐）**：配置好语音转写服务后，点击麦克风按钮直接语音回答
   - **方式二（便捷）**：使用手机/电脑输入法的「语音转文字」功能，将回答输入到文本框中
   - **方式三**：直接手动输入文字回答
5. 提交后，AI 会从多个维度评分并提供针对性改进建议
6. 查看历史练习记录，分析进步趋势

**行测错题管理**：

1. 在「行测题库」中添加错题
2. 标记题型、正确答案和解析
3. 系统自动统计各题型正确率，推荐重点复习方向

## AI 配置

应用可以**无需 API key 运行**，AI 回复会使用规则降级模式。

### 数据安全提示

> ? **重要**：AI API 的数据处理方式取决于你配置的服务类型：
>
> - **本地模型（推荐）**：如使用本地部署的模型（如 Ollama、LM Studio），所有数据在本地处理，可以放心记录敏感信息
> - **云端 API**：如使用云服务商的 API（Anthropic、OpenAI 等），数据会发送到云端处理，**不建议输入敏感个人信息**
>
> 建议有隐私需求的用户使用本地模型，或启用规则降级模式（不配置 API key）

### 配置 AI API

启用完整 AI 功能，编辑 `.env`：

```env
ANTHROPIC_API_KEY=your-key
ANTHROPIC_BASE_URL=your-compatible-endpoint
```

登录后，管理员也可以在 `/settings` 的「内置 AI API」区域修改配置，保存后热重载生效。

## 语音转写（可选）

支持 OpenAI 兼容的 `/audio/transcriptions` 接口。可接 OpenAI 官方，也可接本地免费开源服务：

### 启动本地语音转写服务

```powershell
docker compose -f docker-compose.faster-whisper.yml up -d
```

### 配置 .env

```env
SPEECH_TO_TEXT_PROVIDER=openai
OPENAI_API_KEY=local-key-can-be-any-non-empty-value
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_TRANSCRIBE_MODEL=Systran/faster-whisper-small
```

> **提示**：如果不配置语音转写，面试练习时可以直接使用输入法的语音转文字功能，同样方便！

## 多设备访问

### 方式一：内网穿透（适合个人临时使用）

使用内网穿透工具将本地服务映射到公网：

```powershell
# 示例：使用 Cloudflare Tunnel
cloudflared tunnel --url http://127.0.0.1:5000
```

然后在 `.env` 中配置：

```env
PUBLIC_ACCESS=true
ALLOW_PUBLIC_REGISTRATION=false  # 关闭公开注册，更安全
SESSION_COOKIE_SECURE=true
```

### 方式二：部署到服务器（适合长期使用）

**云服务器部署**：

1. 购买云服务器（阿里云、腾讯云等）
2. 安装 Python 环境
3. 上传项目代码
4. 配置 Nginx 反向代理（可选）
5. 使用域名访问

**配置生产环境**：

```env
APP_ENV=production
FLASK_DEBUG=false
HOST=0.0.0.0
SECRET_KEY=生产环境必须使用强随机密钥
```

## 项目亮点

| 亮点 | 说明 |
|------|------|
| 零门槛启动 | Windows 双击即可运行，无需技术背景 |
| 离线可用 | 不配置 AI 也能使用，功能完整 |
| 数据安全 | 所有数据存储在本地，不上传第三方 |
| 四圣谏言 | 独创的思维框架，深度省察每一天 |
| 面试实战 | 模拟真实面试场景，AI 评分反馈 |
| 进步可视化 | 图表展示情绪变化、学习进步趋势 |
| 多端适配 | 支持内网穿透，手机随时可用 |

## 安全说明

这个仓库是脱敏后的公开版本

请复制 `.env.example` 为 `.env` 后再填入自己的密钥。

## 运行测试

```powershell
python -m unittest discover tests -v
```

## 许可证

本项目采用 [PolyForm Noncommercial License 1.0.0](LICENSE)。

- 允许个人学习、研究、测试、非商业自用
- 允许非商业组织按许可证使用
- 商业使用、公司内部部署、二次开发销售、SaaS 服务化部署等，需要先获得作者书面授权

Commercial use requires prior written permission from the author.

## 发布前检查

```powershell
git status --short
git ls-files
```

确认不要提交 `.env`、`data/`、`static/uploads/`、日志和缓存。
