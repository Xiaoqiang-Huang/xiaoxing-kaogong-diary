"""
日记智能问答引擎
支持：时间查询、关键词搜索、AI智能问答
"""
import re
import logging
from datetime import datetime, timedelta
from dateutil.parser import parse as parse_date
from collections import defaultdict

logger = logging.getLogger(__name__)


class TimeParser:
    """时间表达式解析器"""

    # 时间关键词映射
    TIME_KEYWORDS = {
        '今天': 0,
        '昨天': -1,
        '前天': -2,
        '大前天': -3,
        '本周': 'week',
        '上周': 'last_week',
        '这周': 'week',
        '这个月': 'month',
        '这个月': 'month',
        '最近': 'recent',
        '近期': 'recent',
    }

    @staticmethod
    def parse(time_str, base_date=None):
        """
        解析时间表达式
        返回: (start_date, end_date) 或 None
        """
        if not base_date:
            base_date = datetime.now().date()

        time_str = time_str.strip()

        # 1. 关键词解析
        for keyword, offset in TimeParser.TIME_KEYWORDS.items():
            if keyword in time_str:
                if isinstance(offset, int):
                    # 具体天数
                    target_date = base_date + timedelta(days=offset)
                    return (target_date, target_date)
                elif offset == 'week':
                    # 本周
                    start = base_date - timedelta(days=base_date.weekday())
                    end = start + timedelta(days=6)
                    return (start, end)
                elif offset == 'last_week':
                    # 上周
                    start = base_date - timedelta(days=base_date.weekday() + 7)
                    end = start + timedelta(days=6)
                    return (start, end)
                elif offset == 'month':
                    # 本月
                    start = base_date.replace(day=1)
                    next_month = start.replace(month=start.month % 12 + 1, day=1) if start.month < 12 else start.replace(year=start.year + 1, month=1, day=1)
                    end = next_month - timedelta(days=1)
                    return (start, end)
                elif offset == 'recent':
                    # 最近7天
                    start = base_date - timedelta(days=7)
                    end = base_date
                    return (start, end)

        # 2. 日期格式解析 (YYYY-MM-DD, YYYY年MM月DD日)
        date_patterns = [
            r'(\d{4})-(\d{1,2})-(\d{1,2})',  # YYYY-MM-DD
            r'(\d{4})年(\d{1,2})月(\d{1,2})日',  # 中文格式
            r'(\d{4})\.(\d{1,2})\.(\d{1,2})',  # YYYY.MM.DD
        ]

        for pattern in date_patterns:
            match = re.search(pattern, time_str)
            if match:
                year, month, day = match.groups()
                try:
                    target_date = datetime(int(year), int(month), int(day)).date()
                    return (target_date, target_date)
                except:
                    pass

        # 3. 月份/年份解析
        month_match = re.search(r'(\d{4})年(\d{1,2})月', time_str)
        if month_match:
            year, month = month_match.groups()
            import calendar
            _, last_day = calendar.monthrange(int(year), int(month))
            start = datetime(int(year), int(month), 1).date()
            end = datetime(int(year), int(month), last_day).date()
            return (start, end)

        year_match = re.search(r'(\d{4})年', time_str)
        if year_match:
            year = int(year_match.group(1))
            start = datetime(year, 1, 1).date()
            end = datetime(year, 12, 31).date()
            return (start, end)

        return None


class DiarySearcher:
    """日记搜索引擎"""

    def __init__(self, db):
        self.db = db

    def search_by_time(self, user_id, time_range):
        """
        按时间范围搜索
        time_range: (start_date, end_date) 或 None
        """
        from models import Diary

        if not time_range:
            return []

        start, end = time_range
        start_str = start.strftime('%Y-%m-%d')
        end_str = end.strftime('%Y-%m-%d')

        results = Diary.query.filter_by(user_id=user_id)\
            .filter(Diary.date >= start_str)\
            .filter(Diary.date <= end_str)\
            .order_by(Diary.date.desc())\
            .all()

        return results

    def search_by_keywords(self, user_id, keywords):
        """按关键词搜索"""
        from models import Diary

        # 构建查询条件
        query = Diary.query.filter_by(user_id=user_id)

        # 多个关键词用OR连接
        conditions = []
        for keyword in keywords:
            conditions.append(Diary.content.contains(keyword))

        if conditions:
            from sqlalchemy import or_
            query = query.filter(or_(*conditions))

        results = query.order_by(Diary.date.desc()).all()

        return results

    def search_by_mention(self, user_id, mention):
        """搜索特定提及其中的内容（如人名、项目名）"""
        from models import Diary

        results = Diary.query.filter_by(user_id=user_id)\
            .filter(Diary.content.contains(mention))\
            .order_by(Diary.date.desc())\
            .all()

        return results


class QueryEngine:
    """智能问答引擎"""

    def __init__(self, db, ai_engine):
        self.db = db
        self.ai_engine = ai_engine
        self.time_parser = TimeParser()
        self.searcher = DiarySearcher(db)

    def classify_question(self, question):
        """
        分类问题类型
        返回: 'memory', 'daily_report', 'profile', 'time_query', 'keyword_search', 'topic_track', 'stats', 'chat'
        """
        question_lower = question.lower()

        memory_keywords = ['待办', '未完成', '没做完', '还没做', '还没完成', '提醒', '承诺', '明天要做', '接下来做', '我还有什么事', '哪些事情没做']
        if any(kw in question for kw in memory_keywords):
            return 'memory'

        report_keywords = ['日报', '每日简报', '资讯', '新闻', '重复', '昨天日报', '历史报告']
        if any(kw in question for kw in report_keywords):
            return 'daily_report'

        # 个人信息/画像类问题（优先级最高）
        profile_keywords = ['个人信息', '我的信息', '介绍自己', '自我介绍',
                           '我是谁', '关于我', '我的情况', '我的背景',
                           '你是谁', '我是什么样的人', '我的性格']
        if any(kw in question for kw in profile_keywords):
            return 'profile'

        # 总结类问题
        summary_keywords = ['总结一下', '概括', '总体', '整体情况']
        if any(kw in question for kw in summary_keywords):
            return 'profile'

        # 时间查询特征
        time_keywords = ['昨天', '今天', '前天', '本周', '上周', '最近', '近期',
                       '年', '月', '日', '周', '什么时候', '哪天']
        if any(kw in question for kw in time_keywords):
            return 'time_query'

        # 统计分析特征
        stats_keywords = ['怎么样', '如何', '趋势', '平均', '统计', '多久', '频率']
        if any(kw in question for kw in stats_keywords):
            return 'stats'

        # 主题追踪特征
        track_keywords = ['变化', '演变', '发展', '过程', '历史', '经历']
        if any(kw in question for kw in track_keywords):
            return 'topic_track'

        # 默认为关键词搜索
        return 'keyword_search'

    def extract_keywords(self, question):
        """提取问题中的关键词"""
        question_clean = question or ""
        for phrase in [
            '请问', '帮我', '查询', '搜索', '找一下', '看一下', '分析一下',
            '什么', '怎么', '如何', '哪些', '多少', '为什么', '有没有',
            '吗', '呢', '啊', '吧', '一下'
        ]:
            question_clean = question_clean.replace(phrase, ' ')

        question_clean = re.sub(
            r'(最近|近期|今天|昨天|前天|本周|上周|这个月|上个月|今年|去年|日记|记录|内容|情况|事情|时候|关于|里面|我的|我)',
            ' ',
            question_clean
        )

        words = re.findall(r'[A-Za-z0-9_+\-#]{2,}|[一-龥]{2,}', question_clean)

        stop_words = {
            '日记', '记录', '事情', '内容', '时候', '昨天', '今天', '最近',
            '查询', '搜索', '分析', '总结', '一下', '哪些', '什么', '情况'
        }
        keywords = [w.strip() for w in words if w.strip() and w.strip() not in stop_words]

        return keywords[:5]  # 最多5个关键词

    def answer(self, question, user_id):
        """
        回答问题
        返回: {
            'answer': str,
            'type': str,
            'sources': list
        }
        """
        logger.info(f"问答: {question}")

        # 1. 分类问题
        q_type = self.classify_question(question)

        # 2. 提取关键词
        keywords = self.extract_keywords(question)

        # 3. 根据类型处理
        if q_type == 'memory':
            return self._answer_memory(question, user_id)
        elif q_type == 'daily_report':
            return self._answer_daily_report(question, user_id)
        elif q_type == 'profile':
            return self._answer_profile(question, user_id)
        elif q_type == 'time_query':
            return self._answer_time_query(question, user_id)
        elif q_type == 'keyword_search':
            return self._answer_keyword_search(question, keywords, user_id)
        elif q_type == 'topic_track':
            return self._answer_topic_track(question, keywords, user_id)
        elif q_type == 'stats':
            return self._answer_stats(question, keywords, user_id)
        else:
            return self._answer_chat(question, user_id)

    def _answer_memory(self, question, user_id):
        """回答待办/长期记忆相关问题。"""
        from models import MemoryItem

        include_done = any(kw in question for kw in ['完成了什么', '已完成', '做完'])
        query = MemoryItem.query.filter_by(user_id=user_id, item_type='todo')
        if not include_done:
            query = query.filter_by(status='open')
        items = query.order_by(MemoryItem.due_date.is_(None), MemoryItem.due_date.asc(), MemoryItem.updated_at.desc()).limit(20).all()

        if not items:
            return {
                'answer': '目前没有记录到未完成事项。你可以在日记里写“明天要……”“还没做完……”，我会自动记住并在后续提醒。',
                'type': 'memory',
                'sources': []
            }

        open_items = [item for item in items if item.status == 'open']
        done_items = [item for item in items if item.status == 'done']
        lines = []
        if open_items:
            lines.append('你当前还没做完的事项：')
            for idx, item in enumerate(open_items, start=1):
                due = f'（{item.due_date}）' if item.due_date else ''
                lines.append(f'{idx}. {item.title}{due}')
        if include_done and done_items:
            lines.append('\n最近已完成：')
            for item in done_items[:5]:
                lines.append(f'- {item.title}')

        lines.append('\n完成后直接告诉我“完成了 xxx”，我会帮你从未完成列表里划掉。')
        return {
            'answer': '\n'.join(lines),
            'type': 'memory',
            'sources': []
        }

    def _answer_daily_report(self, question, user_id):
        """回答日报/资讯重复相关问题。"""
        from models import DailyReport

        reports = DailyReport.query.filter_by(user_id=user_id)\
            .order_by(DailyReport.report_date.desc(), DailyReport.created_at.desc()).limit(5).all()
        if not reports:
            return {
                'answer': '还没有历史日报。你可以先点“日报”生成一份，我后续会用历史报告做去重，尽量避免昨天看过的资讯重复出现。',
                'type': 'daily_report',
                'sources': []
            }

        payload = []
        for report in reports:
            content = (report.content or '')[:1600]
            payload.append(f"日期：{report.report_date}\n摘要：{report.summary or ''}\n内容节选：{content}")

        prompt = f"""用户问：{question}

下面是用户最近的日报记录：
{chr(10).join(payload)}

请回答用户关于日报、资讯新鲜度、重复内容或历史报告的问题。
要求：
1. 先基于已有日报说事实，不要编造不存在的新闻。
2. 如果用户问重复，指出可能重复的话题或来源。
3. 给出下一步改进建议，控制在250字以内。"""
        try:
            ai_response = self.ai_engine.chat(prompt, user_id=user_id)
            answer = ai_response.get('reply') or ''
        except Exception as e:
            logger.error(f"AI日报查询失败: {e}")
            answer = f"最近有 {len(reports)} 份日报，最新一份是 {reports[0].report_date}。如果你问重复内容，我会优先对比最近几天的标题和链接。"

        return {
            'answer': answer,
            'type': 'daily_report',
            'sources': []
        }

    def _answer_profile(self, question, user_id):
        """处理个人信息/画像类问题 - 使用AI深度分析"""
        from models import Diary

        # 获取用户最近的日记（越多越好，用于全面分析）
        recent_diaries = Diary.query.filter_by(user_id=user_id)\
            .order_by(Diary.date.desc()).limit(20).all()

        if not recent_diaries:
            return {
                'answer': '还没有日记记录，无法分析你的个人信息。多记录一些日记后，我就能更好地了解你了！',
                'type': 'profile',
                'sources': []
            }

        # 准备AI分析内容
        diaries_for_ai = []
        for diary in recent_diaries:
            diaries_for_ai.append(f"""
日期: {diary.date}
内容: {diary.content[:1000]}
""")

        diaries_text = "\n".join(diaries_for_ai)

        # 让AI进行全面的用户画像分析
        ai_prompt = f"""用户问：{question}

请仔细阅读以下日记内容，为用户生成一份全面的个人画像分析：

{diaries_text}

请从以下维度进行分析：
1. **基本信息**：身份、职业、学习方向
2. **核心关注点**：在哪些领域投入精力
3. **性格特点**：从记录方式、内容风格推断
4. **日常习惯**：学习/工作模式、作息规律
5. **近期状态**：最近的重点事项和心态
6. **价值观/理念**：从内容中体现的思考方式

要求：
- 用自然、友好的语言
- 基于事实推理，不要瞎猜
- 控制在400字以内
- 用emoji让回答更生动"""

        try:
            ai_response = self.ai_engine.chat(ai_prompt, user_id=user_id)
            answer = ai_response.get('reply', '抱歉，分析失败。')
        except Exception as e:
            logger.error(f"AI画像分析失败: {e}")
            # 降级方案
            total = len(recent_diaries)
            date_range = f"{recent_diaries[-1].date} 到 {recent_diaries[0].date}"
            answer = f"你记录了 {total} 篇日记（{date_range}）。多记录一些内容，我就能更好地分析你的个人情况了。"

        sources = [{'date': d.date, 'id': d.id} for d in recent_diaries[:10]]

        return {
            'answer': answer,
            'type': 'profile',
            'sources': sources
        }

    def _answer_time_query(self, question, user_id):
        """处理时间查询 - 使用AI深度总结"""
        # 解析时间
        time_range = self.time_parser.parse(question)

        if not time_range:
            return {
                'answer': '抱歉，我没理解你说的时间。可以试试说"昨天"、"上周"、"2024年1月"等。',
                'type': 'time_query',
                'sources': []
            }

        # 搜索日记
        results = self.searcher.search_by_time(user_id, time_range)

        if not results:
            return {
                'answer': f'这段时间没有找到日记记录。',
                'type': 'time_query',
                'sources': []
            }

        # 准备AI总结所需的内容
        start, end = time_range

        # 构建日记摘要（用于AI阅读）
        diaries_for_ai = []
        for diary in results[:15]:  # 最多15篇
            diaries_for_ai.append(f"""
日期: {diary.date}
内容: {diary.content[:1000]}  # 限制长度避免token过多
""")

        diaries_text = "\n".join(diaries_for_ai)

        # 让AI总结
        ai_prompt = f"""请仔细阅读以下日记内容，回答用户的问题：「{question}」

日记内容：
{diaries_text}

请用自然、流畅的语言总结。要求：
1. 提取关键事件和进展
2. 识别主题和趋势
3. 如果有变化，请指出变化过程
4. 不要简单列举，要用连贯的叙述

总结字数控制在300字以内。"""

        try:
            ai_response = self.ai_engine.chat(ai_prompt, user_id=user_id)
            answer = ai_response.get('reply', '')
        except Exception as e:
            logger.error(f"AI总结失败: {e}")
            # 降级方案：简单列举
            answer = f"在 {start} 到 {end} 之间，找到了 {len(results)} 篇日记：\n\n"
            for diary in results[:5]:
                events = self._extract_events(diary.content)
                if events:
                    answer += f"- {diary.date}: {', '.join(events[:2])}\n"

        sources = [{'date': d.date, 'id': d.id} for d in results]

        return {
            'answer': answer,
            'type': 'time_query',
            'sources': sources
        }

    def _answer_keyword_search(self, question, keywords, user_id):
        """处理关键词搜索 - 使用AI深度总结"""
        if not keywords:
            return {
                'answer': '能告诉我你想搜索什么关键词吗？',
                'type': 'keyword_search',
                'sources': []
            }

        # 搜索日记
        results = self.searcher.search_by_keywords(user_id, keywords)

        if not results:
            return {
                'answer': f'没有找到包含"{", ".join(keywords)}"的日记。',
                'type': 'keyword_search',
                'sources': []
            }

        # 准备AI总结所需的内容
        diaries_for_ai = []
        for diary in results[:10]:  # 最多10篇
            diaries_for_ai.append(f"""
日期: {diary.date}
内容: {diary.content[:800]}
""")

        diaries_text = "\n".join(diaries_for_ai)

        # 让AI总结
        ai_prompt = f"""请仔细阅读以下日记内容，回答用户的问题：「{question}」

关键词：{', '.join(keywords)}

日记内容：
{diaries_text}

请用自然、流畅的语言总结。要求：
1. 围绕关键词提取相关信息
2. 识别相关事件和观点
3. 如果有变化或趋势，请指出
4. 不要简单列举，要用连贯的叙述

总结字数控制在250字以内。"""

        try:
            ai_response = self.ai_engine.chat(ai_prompt, user_id=user_id)
            answer = ai_response.get('reply', '')
        except Exception as e:
            logger.error(f"AI总结失败: {e}")
            # 降级方案：简单列举
            answer = f"找到 {len(results)} 篇关于 {', '.join(keywords)} 的日记：\n\n"
            for diary in results[:5]:
                snippet = self._extract_snippet(diary.content, keywords)
                answer += f"- {diary.date}: {snippet}\n"

        sources = [{'date': d.date, 'id': d.id} for d in results]

        return {
            'answer': answer,
            'type': 'keyword_search',
            'sources': sources
        }

    def _answer_topic_track(self, question, keywords, user_id):
        """处理主题追踪 - 使用AI分析变化"""
        if not keywords:
            return self._answer_keyword_search(question, keywords, user_id)

        # 搜索相关日记，按时间排序
        from models import Diary
        from sqlalchemy import or_

        conditions = [Diary.content.contains(kw) for kw in keywords]
        results = Diary.query.filter_by(user_id=user_id)\
            .filter(or_(*conditions))\
            .order_by(Diary.date.asc())\
            .all()  # 按时间正序排列，便于分析变化

        if len(results) < 2:
            return {
                'answer': f'关于{", ".join(keywords)}的记录太少，无法分析变化。只有 {len(results)} 篇相关日记。',
                'type': 'topic_track',
                'sources': [{'date': d.date, 'id': d.id} for d in results]
            }

        # 用AI分析变化（完整内容，按时间顺序）
        diaries_text = "\n\n---\n\n".join([
            f"日期: {d.date}\n内容: {d.content[:1000]}"
            for d in results[:12]
        ])

        ai_prompt = f"""用户问：{question}

关键词：{', '.join(keywords)}

请按时间顺序分析以下日记，识别用户关于"{", ".join(keywords)}"的态度/观点/行为的演变过程：

{diaries_text}

请重点分析：
1. 初始态度/状态是什么？
2. 中间经历了哪些关键转折点？
3. 当前状态/结论是什么？
4. 整体趋势是积极的、消极的，还是复杂混合的？

用自然流畅的语言总结，250字以内。"""

        try:
            ai_response = self.ai_engine.chat(ai_prompt, user_id=user_id)
            answer = ai_response.get('reply', '无法分析变化。')
        except Exception as e:
            logger.error(f"AI分析变化失败: {e}")
            # 降级方案：简单列举
            answer = f"关于{", ".join(keywords)}的变化记录：\n"
            for d in results[:5]:
                events = self._extract_events(d.content)
                if events:
                    answer += f"- {d.date}: {', '.join(events[:2])}\n"

        return {
            'answer': answer,
            'type': 'topic_track',
            'sources': [{'date': d.date, 'id': d.id} for d in results]
        }

    def _answer_stats(self, question, keywords, user_id):
        """处理统计分析 - 使用AI深度分析"""
        from models import Diary

        if keywords:
            results = self.searcher.search_by_keywords(user_id, keywords)

            if not results:
                return {
                    'answer': f'关于{", ".join(keywords)}，没有找到相关记录。',
                    'type': 'stats',
                    'sources': []
                }

            # 准备AI分析内容
            diaries_for_ai = []
            for diary in results[:10]:
                diaries_for_ai.append(f"""
日期: {diary.date}
内容: {diary.content[:600]}
""")

            diaries_text = "\n".join(diaries_for_ai)

            ai_prompt = f"""请分析用户关于"{", ".join(keywords)}"的记录情况：

问题：{question}

日记内容：
{diaries_text}

请提供：
1. 记录频率和趋势
2. 态度/观点的变化（如果有）
3. 关键发现或洞察

要求自然流畅，200字以内。"""

            try:
                ai_response = self.ai_engine.chat(ai_prompt, user_id=user_id)
                answer = ai_response.get('reply', f'关于{", ".join(keywords)}，你记录了 {len(results)} 篇日记。')
            except Exception as e:
                logger.error(f"AI分析失败: {e}")
                answer = f'关于{", ".join(keywords)}，你记录了 {len(results)} 篇日记。'

            return {
                'answer': answer,
                'type': 'stats',
                'sources': [{'date': d.date, 'id': d.id} for d in results]
            }
        else:
            # 总体统计
            total = Diary.query.filter_by(user_id=user_id).count()
            first_diary = Diary.query.filter_by(user_id=user_id).order_by(Diary.date.asc()).first()

            # 获取最近一些日记做总结
            recent = Diary.query.filter_by(user_id=user_id).order_by(Diary.date.desc()).limit(5).all()

            diaries_for_ai = [f"""日期: {d.date}\n内容: {d.content[:500]}""" for d in recent]
            diaries_text = "\n".join(diaries_for_ai)

            ai_prompt = f"""用户问：{question}

总体情况：共{total}篇日记，第一篇在{first_diary.date if first_diary else '未知'}

最近5篇日记：
{diaries_text}

请总结用户的总体状态和近期趋势。150字以内。"""

            try:
                ai_response = self.ai_engine.chat(ai_prompt, user_id=user_id)
                answer = ai_response.get('reply', f'你总共记录了 {total} 篇日记。')
            except Exception as e:
                answer = f'你总共记录了 {total} 篇日记。你的第一篇日记在 {first_diary.date if first_diary else "未知"}。'

            return {
                'answer': answer,
                'type': 'stats',
                'sources': []
            }

    def _answer_chat(self, question, user_id):
        """普通聊天，转给AI"""
        response = self.ai_engine.chat(question, user_id=user_id)
        return {
            'answer': response.get('reply', '抱歉，我没理解。'),
            'type': 'chat',
            'sources': []
        }

    def _extract_events(self, content):
        """从日记中提取事件"""
        events = []
        lines = content.split('\n')
        in_events = False
        for line in lines:
            if '今日要事' in line or '### 今日要事' in line:
                in_events = True
                continue
            if in_events:
                if line.strip().startswith('---') or line.strip().startswith('##'):
                    break
                if line.strip() and not line.startswith('#'):
                    clean_line = re.sub(r'^[\s\-\*\d\.]+', '', line.strip())
                    if clean_line and len(clean_line) > 2:
                        events.append(clean_line[:50])
        return events[:3]

    def _extract_snippet(self, content, keywords):
        """提取包含关键词的片段"""
        for keyword in keywords:
            if keyword in content:
                idx = content.find(keyword)
                start = max(0, idx - 20)
                end = min(len(content), idx + 50)
                snippet = content[start:end]
                # 移除markdown符号
                snippet = re.sub(r'[#*`\[\]]', '', snippet)
                return snippet.strip()
        return "..." + content[:30] + "..."


# 全局实例
query_engine = None


def init_query_engine(db, ai_engine):
    """初始化问答引擎"""
    global query_engine
    query_engine = QueryEngine(db, ai_engine)
    return query_engine
