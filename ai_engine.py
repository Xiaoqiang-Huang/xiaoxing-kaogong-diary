"""
AI对话引擎 - 四圣谏言引导式日记记录
"""
import os
import json
import logging
import base64
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局变量（用于访问数据库）
_db = None
_user_model = None


def init_ai_engine(db, User):
    """初始化AI引擎，注入数据库模型"""
    global _db, _user_model
    _db = db
    _user_model = User

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic库未安装，AI功能将使用模拟回复")


class FourSagesEngine:
    """四圣谏言对话引擎"""

    def __init__(self, api_key=None, base_url=None):
        """初始化引擎"""
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY', '')
        self.base_url = base_url or os.environ.get('ANTHROPIC_BASE_URL', '')
        self.client = None

        if ANTHROPIC_AVAILABLE and self.api_key:
            try:
                if self.base_url:
                    # 使用自定义端点
                    self.client = anthropic.Anthropic(
                        api_key=self.api_key,
                        base_url=self.base_url
                    )
                    logger.info(f"AI引擎已连接: {self.base_url}")
                else:
                    self.client = anthropic.Anthropic(api_key=self.api_key)
                    logger.info("AI引擎已连接: Claude API")
            except Exception as e:
                logger.error(f"Claude API初始化失败: {e}")

        # 对话状态
        self.conversation_stage = "greeting"  # greeting, events, reflection, sages, summary
        self.collected_info = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "events": [],
            "mood": None,
            "energy": None,
            "sleep": None,
            "reflections": []
        }

    def is_available(self):
        """检查AI是否可用"""
        return self.client is not None

    def _model_candidates(self):
        """模型候选列表，普通调用和流式调用共用。"""
        return [
            "claude-sonnet-4-20250514",
            "claude-sonnet-4-20250114",
            "claude-3-5-sonnet-20241022",
            "claude-3-sonnet-20240229"
        ]

    def _get_user_context(self, user_id):
        """获取用户上下文信息"""
        if not _db or not _user_model:
            return ""

        try:
            from models import Diary, InterviewRecord

            # 获取用户最近的5篇日记（在Flask请求上下文中执行）
            recent_diaries = Diary.query.filter_by(user_id=user_id)\
                .order_by(Diary.date.desc()).limit(5).all()

            if not recent_diaries:
                return "这是用户第一次记录日记。"

            # 构建上下文摘要
            context_parts = []
            context_parts.append(f"## 用户最近记录摘要\n")

            for diary in recent_diaries[:3]:  # 只取最近3篇
                # 提取关键信息
                content = diary.content
                date = diary.date

                # 提取"今日要事"
                events = []
                if '今日要事' in content:
                    lines = content.split('\n')
                    in_events = False
                    for line in lines:
                        if '今日要事' in line:
                            in_events = True
                            continue
                        if in_events:
                            if line.strip().startswith('-') or line.strip().startswith('###'):
                                break
                            if line.strip() and not line.startswith('#'):
                                events.append(line.strip()[:50])  # 截取前50字符

                context_parts.append(f"- {date}: {', '.join(events[:3]) if events else '日常记录'}")

            interview_records = InterviewRecord.query.filter_by(user_id=user_id)\
                .order_by(InterviewRecord.created_at.desc()).limit(6).all()
            if interview_records:
                context_parts.append("\n## 最近面试评价")
                scores = []
                weaknesses = []
                for record in interview_records:
                    evaluation = record.get_ai_evaluation()
                    score = evaluation.get('overall_score') or evaluation.get('score')
                    try:
                        scores.append(float(score))
                    except (TypeError, ValueError):
                        pass
                    weaknesses.extend(evaluation.get('weaknesses') or [])
                    summary = evaluation.get('objective_assessment') or evaluation.get('summary') or ''
                    context_parts.append(
                        f"- {record.created_at.strftime('%Y-%m-%d')} {record.category}: "
                        f"{score or '未评分'}分，{summary[:80]}"
                    )
                if scores:
                    context_parts.append(f"- 面试近况：最近{len(scores)}次平均 {sum(scores) / len(scores):.1f}/10。")
                if weaknesses:
                    context_parts.append(f"- 高频短板：{'；'.join(weaknesses[:4])}")

            return '\n'.join(context_parts) + '\n'

        except Exception as e:
            logger.error(f"获取用户上下文失败: {e}")
            return ""

    def _get_user_display_name(self, user_id):
        """Return the safest available name for addressing the current user."""
        if not user_id or not _user_model:
            return "用户"

        try:
            user = _db.session.get(_user_model, user_id) if _db else _user_model.query.get(user_id)
            if not user:
                return "用户"

            for attr in ("display_name", "nickname", "name", "username"):
                value = getattr(user, attr, None)
                if value and str(value).strip():
                    return str(value).strip()
        except Exception as e:
            logger.error(f"获取用户称呼失败: {e}")

        return "用户"

    def get_system_prompt(self, user_id=None, style='four_sages', custom_style_prompt=None):
        """获取系统提示词（包含用户上下文）

        设计理念：
        1. 基底：温柔温暖，无emoji
        2. 叠加：所选风格在温柔基底之上
        """

        # 基底：温柔风格 + 无emoji + 客观评价后鼓励
        display_name = self._get_user_display_name(user_id)
        base_gentle = f"""你是{display_name}的日记助手，是当前用户值得信赖的朋友。

【称呼规则】
- 当前用户称呼：{display_name}
- 开场和对话中按当前用户称呼对方；如果不确定真实姓名，就用账号名或“你”。
- 不要把所有用户都叫作某个固定昵称，除非当前用户自己的称呼就是这个名字。

【基底风格（必须严格遵循）】
- 温柔、温暖、友善的语气
- 无论如何都要保持耐心和善意
- 绝对不要使用emoji表情符号，用文字表达情感
- 简洁但真诚，像真正的朋友
- 理解他的处境，给予支持

【鼓励原则：客观评价后的真诚鼓励】
- 首先客观分析情况，指出真实的问题和现状
- 不回避问题，不美化现实，不进行虚假表扬
- 在客观认知的基础上，给出有针对性的鼓励
- 鼓励要具体、有依据，指出他真实的努力和进步
- 示例模式："今天确实没有完成计划（客观），但你能意识到这一点并记录下来（真实进步），明天可以调整节奏（具体建议）"
- 示例模式："这个方法确实效果有限（客观评价），但你愿意尝试新思路的勇气值得肯定（真实优点），我们换个角度试试（具体行动）"
- 避免模式："你真棒"、"太厉害了"、"你是最棒的"（空洞表扬）

【评价输出顺序】
当用户要求评价、复盘、建议、考公练习反馈，或表达自我否定时，按这个顺序回应：
1. 客观评价：先说事实、问题、风险或完成度，语气平实。
2. 值得肯定：指出他本次真实做到了什么，例如记录、开口练习、发现问题、持续尝试。
3. 下一步行动：给一个小而具体的行动，最好今天或明天就能做。

不要只指出问题后结束。每次客观评价之后，都要给出一段有依据的鼓励，让他知道自己可以从哪里继续推进。

【对话目标】
1. 引导他记录今天的重要事情/想法
2. 给予情感支持和理解
3. 客观分析后给出真诚、有依据的鼓励
4. 必要时追问，但不要一次问太多问题
5. 当他说"完成""结束"时，帮他把对话整理成日记，总结中包含客观评价和真实鼓励

【智能回答规则】
- 先判断用户是在记录、查询、复盘、练习面试、积累申论素材，还是寻求情绪支持。
- 能从用户背景、近期日记、面试评价趋势中找到证据时，要结合证据回答；不要只给通用鸡汤。
- 用户问趋势、原因、短板、下一步时，要输出“观察到的事实 -> 解释 -> 下一步动作”。
- 如果信息不足，只问一个最关键的问题；不要连续抛出多个问题增加负担。
- 默认服务于长期个人战略：日常省察、考公复盘、申论素材、表达训练和能力圈建设。

【重要提醒】
- 你的回复永远不要包含emoji
- 不捧杀，不回避问题
- 在真实认知的基础上给予支持

"""

        # 风格叠加（在温柔基底之上）
        style_overlays = {
            'four_sages': """
【风格叠加：四圣谏言】
当需要深度建议时，可以从以下四位智者的视角给出建议：
- 【曾国藩】：慎独、修己、躬身入局、尚拙
- 【芒格】：逆向思考、多元思维模型、避免认知偏误
- 【巴菲特】：能力圈、长期主义、复利、护城河
- 【Karpathy】：构建即理解、工程现实、可靠性

但不要每次都用四圣谏言格式，看情况灵活运用。保持温柔的基底。
""",

            'zeng': """
【风格叠加：曾国藩修身省察】
- 慎独：独处时的自我约束
- 尚拙：不走捷径，踏实做事
- 躬身入局：亲身实践，不空谈
- 修己：反省自己的过失

以温柔的方式引导他反思自己的行为和动机，而不是说教。
""",

            'munger': """
【风格叠加：芒格逆向思维】
- 逆向思考："反过来想，如何确保失败"
- 多元思维：跨学科知识
- 避免认知偏误：帮他识别思维陷阱
- 激励结构分析：理解行为背后的动机

以温柔的方式引导他反直觉地思考问题，但不要过于尖锐。
""",

            'buffett': """
【风格叠加：巴菲特长期主义】
- 能力圈：做自己擅长的事
- 护城河：建立竞争壁垒
- 复利效应：时间积累的价值
- 20年后看：长期视角

以温柔的方式引导他从长远角度思考，给他耐心和信心。
""",

            'karpathy': """
【风格叠加：Karpathy工程实践】
- 构建即理解：亲手实现才能真正理解
- 可靠性：追求可靠性
- Don't be hero：务实优先，不搞花里胡哨
- 数据驱动：用数据说话

以温柔的方式鼓励他动手实践，但不要过于技术化。
""",

            'gentle': """
【风格叠加：纯粹温柔（最高级别）】
- 专注于倾听和共情
- 情绪确认和接纳
- 给予最温暖的支持
- 不评判，只陪伴

这是最纯粹的温柔风格，没有任何其他要求。只是陪伴和理解。
""",

            'sharp': """
【风格叠加：犀利追问】
- 连续追问"为什么"
- 挑战假设，但态度友善
- 暴露思维盲点，但给予支持
- 激发自我反思

用温柔的语气进行犀利的追问，帮助他深入思考，但不要过于严厉。
""",

            'maozedong': """
【风格叠加：实事求是】
- 先调查研究，再下判断
- 抓主要矛盾，不把次要问题放大
- 从实践中复盘，再回到行动
- 语言要朴素、有力量、能落地

用温柔但清醒的方式帮助用户看清事实、矛盾和下一步行动。
""",

            'mengmei': """
【风格叠加：温柔萌妹】
- 语气轻柔、亲近、会鼓励人
- 先接住情绪，再给客观建议
- 可以可爱一点，但不要撒娇过度
- 不要空夸，要给具体下一步

像一个认真陪伴用户成长的温柔助手，回复靠左排版，内容清楚好读。
"""
        }

        # 组合基底 + 风格叠加
        if style == 'custom' and custom_style_prompt:
            style_addition = f"""
【风格叠加：用户自定义】
用户希望你采用以下表达风格。必须服从基底规则，不得空夸、不得回避问题：
{custom_style_prompt[:1000]}
"""
        else:
            style_addition = style_overlays.get(style, style_overlays['four_sages'])
        base_prompt = base_gentle + style_addition

        # 如果有用户ID，添加用户上下文
        if user_id:
            user_context = self._get_user_context(user_id)
            if user_context:
                base_prompt += f"\n\n## 用户背景信息\n{user_context}"

        return base_prompt

    def chat(self, message, conversation_history=None, user_id=None, style='four_sages', images=None, custom_style_prompt=None):
        """处理用户消息

        Args:
            message: 用户消息
            conversation_history: 对话历史
            user_id: 用户ID
            style: 回复风格 (four_sages, zeng, munger, buffett, karpathy, gentle, sharp)
            images: 图片URL列表（可选）
        """
        logger.info(f"收到消息: {message[:50]}... (风格: {style}, 图片: {len(images) if images else 0})")
        if images:
            logger.info(f"图片URLs: {images}")

        if not self.is_available():
            logger.warning("AI不可用，使用模拟回复")
            return self._mock_response(message)

        # 构建消息列表
        messages = []

        # 添加对话历史（最近20轮，增加了上下文窗口）
        if conversation_history:
            for msg in conversation_history[-20:]:
                if msg.get('role') in ['user', 'assistant']:
                    messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })

        # 添加当前消息
        if images and len(images) > 0:
            # 有图片：构建多模态消息
            content_blocks = [{'type': 'text', 'text': message}]

            # 添加图片
            for img_url in images:
                base64_image = self._image_to_base64(img_url)
                if base64_image:
                    content_blocks.append({
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': self._get_mime_type(img_url),
                            'data': base64_image
                        }
                    })

            messages.append({
                'role': 'user',
                'content': content_blocks
            })
        else:
            # 纯文本消息
            messages.append({
                'role': 'user',
                'content': message
            })

        # 上下文管理：检查是否需要压缩
        if self._should_compress(messages):
            logger.info("上下文接近限制，执行压缩")
            messages = self._compress_history(messages)

        try:
            # 调试：打印消息结构
            for i, msg in enumerate(messages):
                if isinstance(msg.get('content'), list):
                    logger.info(f"消息{i}: 包含{len(msg['content'])}个内容块")
                    for j, block in enumerate(msg['content']):
                        if block.get('type') == 'image':
                            logger.info(f"  图片块{j}: media_type={block['source']['media_type']}, data长度={len(block['source']['data'])}")
                        elif block.get('type') == 'text':
                            logger.info(f"  文本块{j}: {block['text'][:50]}...")

            last_error = None
            for model_name in self._model_candidates():
                try:
                    response = self.client.messages.create(
                        model=model_name,
                        max_tokens=1024,
                        system=self.get_system_prompt(user_id, style, custom_style_prompt),  # 传入style参数
                        messages=messages
                    )
                    reply = response.content[0].text
                    logger.info(f"AI调用成功 (模型: {model_name}, 风格: {style})")
                    return self._format_response(reply)
                except Exception as e:
                    last_error = e
                    logger.warning(f"尝试模型 {model_name} 失败: {e}")
                    continue

            # 所有模型都失败，抛出最后的错误
            raise last_error

        except Exception as e:
            logger.error(f"AI调用失败: {e}")
            import traceback
            traceback.print_exc()
            return self._mock_response(message)

    def stream_chat(self, message, conversation_history=None, user_id=None, style='four_sages', images=None, custom_style_prompt=None):
        """流式处理用户消息，逐段产出文本。"""
        logger.info(f"收到流式消息: {message[:50]}... (风格: {style}, 图片: {len(images) if images else 0})")

        if not self.is_available():
            fallback = self._mock_response(message).get('reply', '')
            if fallback:
                yield fallback
            return

        messages = []
        if conversation_history:
            for msg in conversation_history[-20:]:
                if msg.get('role') in ['user', 'assistant']:
                    messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })

        if images and len(images) > 0:
            content_blocks = [{'type': 'text', 'text': message}]
            for img_url in images:
                base64_image = self._image_to_base64(img_url)
                if base64_image:
                    content_blocks.append({
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': self._get_mime_type(img_url),
                            'data': base64_image
                        }
                    })
            messages.append({'role': 'user', 'content': content_blocks})
        else:
            messages.append({'role': 'user', 'content': message})

        if self._should_compress(messages):
            logger.info("流式上下文接近限制，执行压缩")
            messages = self._compress_history(messages)

        last_error = None
        for model_name in self._model_candidates():
            try:
                with self.client.messages.stream(
                    model=model_name,
                    max_tokens=1024,
                    system=self.get_system_prompt(user_id, style, custom_style_prompt),
                    messages=messages
                ) as stream:
                    for text in stream.text_stream:
                        if text:
                            yield text
                logger.info(f"AI流式调用成功 (模型: {model_name}, 风格: {style})")
                return
            except Exception as e:
                last_error = e
                logger.warning(f"流式尝试模型 {model_name} 失败: {e}")
                continue

        logger.error(f"AI流式调用失败: {last_error}")
        fallback = self._mock_response(message).get('reply', '抱歉，我现在无法回复。')
        if fallback:
            yield fallback

    def _format_response(self, response):
        """格式化AI回复"""
        return {
            'reply': response,
            'stage': self.conversation_stage,
            'can_save': self._check_if_can_save()
        }

    def _check_if_can_save(self):
        """检查是否可以保存为日记"""
        return bool(
            self.collected_info['events'] or
            self.collected_info['reflections']
        )

    def _estimate_tokens(self, messages):
        """估算消息的token数量"""
        total = 0
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get('content', '')
            else:
                content = str(msg)

            # 处理多模态消息（图片+文本）
            if isinstance(content, list):
                # 对于多模态消息，只计算文本部分
                text_content = ''
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        text_content += item.get('text', '')
                content = text_content
            elif not isinstance(content, str):
                content = str(content)

            # 粗略估算：中文约1.5字符/token，英文约4字符/token
            chinese_chars = len([c for c in content if '一' <= c <= '鿿'])
            other_chars = len(content) - chinese_chars
            total += (chinese_chars / 1.5) + (other_chars / 4)
        return int(total)

    def _should_compress(self, messages, max_tokens=80000):
        """检查是否需要压缩上下文"""
        estimated = self._estimate_tokens(messages)
        logger.info(f"估算token数: {estimated}, 限制: {max_tokens}")
        return estimated > max_tokens * 0.8  # 80%时开始压缩

    def _compress_history(self, messages):
        """压缩对话历史，保留关键信息"""
        if len(messages) <= 4:
            return messages

        # 保留最近4条完整消息
        recent_messages = messages[-4:]

        # 生成早期对话的摘要
        early_messages = messages[:-4]
        summary_parts = []
        for msg in early_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            # 每条消息压缩为一句话
            truncated = content[:50] + ('...' if len(content) > 50 else '')
            summary_parts.append(f"{role}: {truncated}")

        summary = {
            'role': 'system',
            'content': f"[早期对话摘要]\n" + "\n".join(summary_parts)
        }

        return [summary] + recent_messages

    def get_topic_recommendations(self, user_id):
        """获取话题推荐 - 基于用户最近的日记，推荐忽视的记录方向"""
        if not _db:
            return []

        try:
            from models import Diary

            # 获取最近20篇日记
            recent_diaries = Diary.query.filter_by(user_id=user_id)\
                .order_by(Diary.date.desc()).limit(20).all()

            if not recent_diaries:
                return [
                    "记录今天的心情",
                    "写下今天发生的一件事",
                    "今天学到什么新东西了吗？",
                    "今天有什么值得感恩的事？"
                ]

            # 分析日记内容，提取话题
            all_content = '\n'.join([d.content for d in recent_diaries])

            # 使用AI分析忽视的话题
            prompt = f"""分析以下日记内容，找出用户可能忽视的记录方向。

日记内容（最近20篇）：
{all_content[:3000]}

请返回3-5个推荐话题，每个话题一行，格式：话题名称
关注点：
1. 哪些生活方面很少被记录？（如：健康、社交、学习、工作、娱乐等）
2. 哪些情绪状态很少出现？
3. 有什么长期目标但进展记录不足？

只返回话题名称，每行一个。"""

            if self.is_available():
                try:
                    response = self.client.messages.create(
                        model="claude-3-5-sonnet-20241022",
                        max_tokens=500,
                        messages=[{"role": "user", "content": prompt}]
                    )

                    result = response.content[0].text
                    recommendations = [line.strip() for line in result.split('\n') if line.strip()]
                    return recommendations[:5] if recommendations else self._default_recommendations()

                except Exception as e:
                    logger.error(f"AI生成话题推荐失败: {e}")

            return self._default_recommendations()

        except Exception as e:
            logger.error(f"获取话题推荐失败: {e}")
            return self._default_recommendations()

    def _default_recommendations(self):
        """默认推荐话题"""
        return [
            "记录今天的身体状况（睡眠、运动、饮食）",
            "写下今天和谁有过互动",
            "今天有什么小确幸或小成就？",
            "记录一个今天的想法或感悟",
            "明天的计划是什么？"
        ]
    def _mock_response(self, message):
        """模拟回复（当AI不可用时）"""
        message_lower = message.lower()

        # 简单的关键词响应（无emoji）
        if any(word in message_lower for word in ['你好', '嗨', 'hi', 'hello']):
            return {
                'reply': f"你好！今天是{self.collected_info['date']}。\n\n今天发生了什么重要的事？或者有什么想记录的？",
                'stage': 'greeting',
                'can_save': False
            }

        elif '累' in message_lower or ' tired' in message_lower:
            self.collected_info['mood'] = 'tired'
            return {
                'reply': "客观说，累不是一个需要硬扛过去的信号，它通常在提醒你：身体、任务量或情绪里至少有一项超载了。\n\n值得肯定的是，你把这个状态说出来了，这比忽略它更容易找到调整办法。\n\n先从一个小问题开始：昨晚睡了几个小时？",
                'stage': 'reflection',
                'can_save': True
            }

        elif '开心' in message_lower or 'happy' in message_lower or '顺利' in message_lower:
            self.collected_info['mood'] = 'happy'
            return {
                'reply': "太好了！能分享一下是什么事情让你感到开心吗？\n\n这样我们可以把它记录下来，以后回看时也能感受到这份心情。",
                'stage': 'reflection',
                'can_save': True
            }

        elif any(word in message_lower for word in ['完成', '总结', 'save', 'end']):
            return {
                'reply': self._generate_summary(),
                'stage': 'summary',
                'can_save': True
            }

        else:
            self.collected_info['events'].append(message)
            return {
                'reply': f"收到了。客观记录下来的是：{message}\n\n值得肯定的是，你没有让这件事只停留在脑子里，而是把它变成了可以复盘的材料。\n\n还有其他想记录的吗？如果没有，可以说「完成」来结束今天的记录。",
                'stage': 'events',
                'can_save': True
            }

    def _generate_summary(self):
        """生成日记总结"""
        events = self.collected_info.get('events', [])
        mood = self.collected_info.get('mood', '平静')

        if not events:
            return """今天的日记内容较少。你可以补充：
- 今天做了什么？
- 有什么特别的感受？
- 明天计划做什么？

或者直接说"完成"保存当前内容。"""

        summary = f"## 今日记录\n\n"
        summary += f"**日期**: {self.collected_info['date']}\n"
        summary += f"**心情**: {mood}\n\n"
        summary += "**今日事件**:\n"
        for i, event in enumerate(events[-5:], 1):  # 最多5条
            summary += f"{i}. {event}\n"

        summary += "\n**客观评价**:\n"
        summary += "今天的记录已经留下了可复盘的事实，但还可以继续补充情绪、原因和下一步行动。\n"
        summary += "\n**鼓励**:\n"
        summary += "你已经完成了最关键的一步：把经历写下来。长期看，这种持续记录会帮助你更清楚地认识自己，也更容易调整行动。\n"
        summary += f"\n日记已记录。回复「确认」保存到数据库。"

        return summary

    def _image_to_base64(self, image_url):
        """将图片URL转换为base64编码

        Args:
            image_url: 图片URL（可以是相对路径如/static/uploads/xxx.jpg）

        Returns:
            base64编码的图片数据（不含data:image前缀）
        """
        try:
            logger.info(f"转换图片到base64: {image_url}")

            # 如果是相对路径，转换为完整URL
            if image_url.startswith('/static/') or image_url.startswith('/static/'):
                # 获取本地文件路径
                filename = os.path.basename(image_url)
                filepath = os.path.join(os.path.dirname(__file__), 'static', 'uploads', filename)

                logger.info(f"本地文件路径: {filepath}, 存在: {os.path.exists(filepath)}")

                if os.path.exists(filepath):
                    with open(filepath, 'rb') as f:
                        image_data = f.read()
                    result = base64.b64encode(image_data).decode('utf-8')
                    logger.info(f"图片转换成功，大小: {len(result)} 字符")
                    return result
                else:
                    logger.warning(f"图片文件不存在: {filepath}")
                    return None
            else:
                # 如果是完整URL，尝试下载（需要requests库）
                try:
                    import requests
                    response = requests.get(image_url, timeout=5)
                    if response.status_code == 200:
                        return base64.b64encode(response.content).decode('utf-8')
                    else:
                        logger.warning(f"下载图片失败: {image_url}")
                        return None
                except ImportError:
                    logger.warning("requests模块未安装，无法下载外部图片")
                    return None

        except Exception as e:
            logger.error(f"图片转base64失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _get_mime_type(self, image_url):
        """根据图片URL获取MIME类型"""
        ext = os.path.splitext(image_url)[1].lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }
        return mime_types.get(ext, 'image/jpeg')


class DiaryAnalyzer:
    """日记分析器 - 集成psychoanalyze模块"""

    def __init__(self):
        """初始化分析器"""
        self.psychoanalyze = None
        self._load_psychoanalyze()

    def _load_psychoanalyze(self):
        """加载心理分析模块"""
        try:
            import sys
            # 添加项目根目录到路径
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from psychoanalyze import analyze_enhanced
            self.analyze_enhanced = analyze_enhanced
            self.psychoanalyze = True
            print("✓ psychoanalyze模块加载成功")
        except ImportError as e:
            print(f"警告: psychoanalyze模块加载失败 - {e}")
            self.psychoanalyze = False

    def analyze(self, content):
        """分析日记内容"""
        if not self.psychoanalyze:
            return self._mock_analysis(content)

        try:
            result = self.analyze_enhanced(content)
            return self._format_analysis(result)
        except Exception as e:
            print(f"分析失败: {e}")
            return self._mock_analysis(content)

    def _format_analysis(self, result):
        """格式化分析结果"""
        # 从result中提取关键信息
        # psychoanalyze返回的是字符串格式的报告
        return {
            'emotion': 'positive',  # 简化处理
            'keywords': [],
            'four_sages': {},
            'full_report': result
        }

    def _mock_analysis(self, content):
        """模拟分析（当模块不可用时）"""
        return {
            'emotion': 'neutral',
            'keywords': ['日记'],
            'four_sages': {
                '曾国藩': '慎独检验：无人监督时，你的表现如何？',
                '芒格': '逆向思考：有什么可能导致今天失败？',
                '巴菲特': '20年视角：这件事20年后看还有意义吗？',
                'Karpathy': '构建即理解：你能从头解释今天做的事吗？'
            },
            'full_report': '（心理分析模块开发中...）'
        }


# 全局实例
four_sages_engine = FourSagesEngine()
diary_analyzer = DiaryAnalyzer()
