"""
面试评价系统 - 结合RAG知识库的智能评价
"""
import json
import re
from typing import Dict, List, Optional
from vector_store import get_knowledge_base
from interview_standards import (
    OFFICIAL_EVALUATION_DIMENSIONS,
    CATEGORY_GUIDANCE,
    get_category_guidance
)


class InterviewEvaluator:
    """面试回答评价器"""

    def __init__(self, ai_engine=None):
        self.knowledge_base = get_knowledge_base()
        self.ai_engine = ai_engine

    def evaluate(self, question: str, answer: str, category: str = "") -> Dict:
        """评价面试回答"""
        # 1. 从知识库检索相关技巧和案例
        context = self.knowledge_base.get_context_for_question(question, category)

        # 2. 构建评价提示词
        prompt = self._build_evaluation_prompt(question, answer, category, context)

        # 3. 调用AI进行评价
        if self.ai_engine and getattr(self.ai_engine, "client", None):
            evaluation = self._ai_evaluate(prompt, answer, category)
        else:
            # 使用规则引擎评价
            evaluation = self._rule_based_evaluate(answer, category)

        return self._normalize_evaluation(evaluation, answer, category)

    def _build_evaluation_prompt(self, question: str, answer: str, category: str, context: str) -> str:
        """构建评价提示词"""
        guidance = get_category_guidance(category)
        dimension_text = "\n".join(
            f"- {name}: {desc}"
            for name, desc in OFFICIAL_EVALUATION_DIMENSIONS.items()
        )
        measured = "、".join(guidance["measured_elements"])
        framework = " -> ".join(guidance["answer_framework"])
        pitfalls = "、".join(guidance["pitfalls"])

        prompt = f"""你是一位专业的公务员面试考官。请对以下面试回答进行评价：

**面试题目**: {question}
**题型**: {guidance["name"]}
**本题重点测评要素**: {measured}
**建议作答框架**: {framework}
**常见失分点**: {pitfalls}
**考生回答**: {answer}
"""

        if context:
            prompt += f"""
**参考资料**:
{context}

请参考上述资料中的答题技巧和要点进行评价。
"""

        prompt += """

公务员面试常见测评要素如下，请优先评价“本题重点测评要素”，并保留“言语表达能力”（每项1-10分）：
""" + dimension_text + """

评价顺序必须是：先客观评价，再指出真实优点，最后给出鼓励和下一步训练。鼓励必须基于考生本次回答里的真实表现，不要写“你很棒”这类空泛表扬。

请用JSON格式回复：
```json
{
    "scores": {
        "综合分析能力": 8,
        "言语表达能力": 7
    },
    "overall_score": 7.8,
    "objective_assessment": "先客观说明本次回答的完成度、主要问题和评分依据",
    "strengths": ["优点1", "优点2"],
    "weaknesses": ["不足1", "不足2"],
    "suggestions": ["改进建议1", "改进建议2"],
    "rubric_notes": {
        "综合分析能力": "逐项说明为什么给这个分数"
    },
    "next_drill": "下一次最该练什么",
    "encouragement": "基于本次真实表现的鼓励，并接上一句可执行的小行动",
    "summary": "总体评价"
}
```
"""
        return prompt

    def _ai_evaluate(self, prompt: str, answer: str = "", category: str = "") -> Dict:
        """使用AI进行评价"""
        try:
            response = self.ai_engine.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text

            # 提取JSON
            json_match = re.search(r'```json\s*({[\s\S]*?})\s*```', content)
            if not json_match:
                json_match = re.search(r'({[\s\S]*})', content)

            if json_match:
                return json.loads(json_match.group(1))
            else:
                return {"summary": content}

        except Exception as e:
            print(f"AI评价失败: {e}")
            return self._rule_based_evaluate(answer, category)

    def _rule_based_evaluate(self, answer: str, category: str) -> Dict:
        """基于规则的评价（备用方案）"""
        answer_len = len(answer)
        word_count = len(answer.replace(' ', ''))
        guidance = get_category_guidance(category)
        score_keys = list(dict.fromkeys(guidance["measured_elements"] + ["言语表达能力"]))

        scores = {key: 6 for key in score_keys}

        # 根据长度调整
        if answer_len < 50:
            for key in scores:
                scores[key] = min(scores[key], 4)
        elif answer_len > 300:
            for key in scores:
                scores[key] = max(scores[key], 7)

        # 检查逻辑连接词
        logic_words = ["首先", "其次", "然后", "最后", "第一", "第二", "一方面", "另一方面", "综上所述", "总之"]
        logic_count = sum(1 for word in logic_words if word in answer)
        if logic_count >= 2:
            for key in ("综合分析能力", "计划组织协调能力", "言语表达能力"):
                if key in scores:
                    scores[key] = max(scores[key], 8)
        elif logic_count >= 1:
            for key in ("综合分析能力", "计划组织协调能力", "言语表达能力"):
                if key in scores:
                    scores[key] = max(scores[key], 7)

        category_keywords = {
            "comprehensive": ["原因", "影响", "对策", "本质", "治理", "落实"],
            "emergency": ["现场", "安抚", "核实", "报告", "处置", "复盘"],
            "interpersonal": ["沟通", "理解", "大局", "工作", "反思", "配合"],
            "organization": ["方案", "分工", "协调", "通知", "预案", "总结"],
            "vocational": ["岗位", "职责", "匹配", "不足", "学习", "服务"],
            "situation": ["您好", "理解", "规定", "材料", "办理", "帮助"],
            "self_intro": ["经历", "优势", "岗位", "匹配", "学习", "服务"],
            "leaderless_group": ["标准", "排序", "共识", "补充", "归纳", "建议"],
            "professional": ["风险", "规范", "数据", "权限", "安全", "整改"]
        }
        hit_count = sum(1 for word in category_keywords.get(category, []) if word in answer)
        if hit_count >= 3:
            for key in guidance["measured_elements"]:
                if key in scores:
                    scores[key] = max(scores[key], 8)
        elif hit_count <= 1 and answer_len >= 80:
            for key in guidance["measured_elements"]:
                if key in scores:
                    scores[key] = min(scores[key], 5)

        # 计算总分
        overall = sum(scores.values()) / len(scores)

        # 生成反馈
        strengths = []
        weaknesses = []
        suggestions = []

        if logic_count >= 2:
            strengths.append("回答有一定的逻辑结构")
        else:
            weaknesses.append("回答缺乏清晰的逻辑结构")
            suggestions.append("建议使用'首先、其次、最后'等连接词组织回答")

        if answer_len > 200:
            strengths.append("回答内容较为充实")
        else:
            weaknesses.append("回答内容偏少")
            suggestions.append("建议展开论述，增加回答的深度和广度")

        if hit_count >= 3:
            strengths.append(f"回答能够贴合{guidance['name']}题型的关键要求")
        else:
            weaknesses.append(f"回答和{guidance['name']}题型的测评要素结合不够")
            suggestions.append("建议按“" + "、".join(guidance["answer_framework"]) + "”组织下一次回答")

        return {
            "scores": scores,
            "overall_score": round(overall, 1),
            "strengths": strengths or ["已经按照题目给出了基本处理思路"],
            "weaknesses": weaknesses or ["可进一步提升"],
            "suggestions": suggestions or ["继续练习，积累经验"],
            "rubric_notes": {
                key: OFFICIAL_EVALUATION_DIMENSIONS.get(key, "")
                for key in scores
            },
            "next_drill": guidance["drill"],
            "summary": "回答基本完成，建议围绕公务员面试测评要素继续提升。"
        }

    def _normalize_evaluation(self, evaluation: Dict, answer: str, category: str) -> Dict:
        """补齐评价结构，确保先客观评价后给出真实鼓励。"""
        if not isinstance(evaluation, dict):
            evaluation = {"summary": str(evaluation)}

        guidance = get_category_guidance(category)
        strengths = self._as_list(evaluation.get("strengths"))
        weaknesses = self._as_list(evaluation.get("weaknesses"))
        suggestions = self._as_list(evaluation.get("suggestions"))

        evaluation["strengths"] = strengths or ["完成了一次完整作答尝试"]
        evaluation["weaknesses"] = weaknesses or ["还可以继续提高内容层次和表达稳定性"]
        evaluation["suggestions"] = suggestions or ["下一轮先按题型框架列出3个要点，再开始作答"]
        evaluation.setdefault("next_drill", guidance["drill"])

        if not evaluation.get("objective_assessment"):
            evaluation["objective_assessment"] = self._build_objective_assessment(evaluation, guidance)

        if not evaluation.get("encouragement"):
            evaluation["encouragement"] = self._build_encouragement(evaluation, answer)

        if not evaluation.get("summary"):
            evaluation["summary"] = "本次回答已经形成基础表达，后续重点是提高结构清晰度和内容贴题度。"

        return evaluation

    @staticmethod
    def _as_list(value) -> List[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    def _build_objective_assessment(self, evaluation: Dict, guidance: Dict) -> str:
        score = self._safe_score(evaluation.get("overall_score"))
        weaknesses = self._as_list(evaluation.get("weaknesses"))

        if score >= 8:
            level = "本次回答整体完成度较高，结构和题型意识已经比较清楚"
        elif score >= 6:
            level = "本次回答基本完成了作答任务，但还需要继续提升层次和展开度"
        else:
            level = "本次回答仍处在起步阶段，主要问题是内容不够充分或结构不够清晰"

        weak_text = "；主要改进点是：" + "；".join(weaknesses[:2]) if weaknesses else ""
        return f"{level}{weak_text}。评价重点按{guidance['name']}题型的测评要素来判断。"

    def _build_encouragement(self, evaluation: Dict, answer: str) -> str:
        strengths = self._as_list(evaluation.get("strengths"))
        next_drill = str(evaluation.get("next_drill") or "继续做一次同题型限时练习").rstrip("。.!！")
        answer_len = len(answer or "")

        if strengths:
            basis = strengths[0]
        elif answer_len > 0:
            basis = "你已经完成了一次开口表达，这比只在脑子里想更接近真实面试"
        else:
            basis = "你愿意进入练习和复盘流程，这是建立面试能力的第一步"

        return f"值得肯定的是，{basis}。这说明你不是停在焦虑里，而是在用练习制造反馈。下一步先抓住一个点：{next_drill}。"

    @staticmethod
    def _safe_score(value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 6.0

    def get_practice_suggestions(self, category: str) -> List[str]:
        """获取针对特定分类的练习建议"""
        guidance = get_category_guidance(category)
        return [
            f"重点测评要素：{'、'.join(guidance['measured_elements'])}",
            f"作答框架：{' -> '.join(guidance['answer_framework'])}",
            f"限时建议：{guidance['time_limit_seconds']}秒内完成",
            f"专项练习：{guidance['drill']}"
        ]


# 预设的模拟面试问题（按难度和分类）
PRACTICE_QUESTIONS = {
    "基础": [
        "请做一个简单的自我介绍。",
        "你为什么报考这个岗位？",
        "你认为你有哪些优势和不足？"
    ],
    "进阶": [
        "有人说'态度决定一切'，也有人说'细节决定成败'。谈谈你的看法。",
        "你刚到一个新岗位，发现同事对你有抵触情绪，你怎么办？",
        "领导交给你一项紧急任务，但你手头还有其他重要工作，你怎么办？"
    ],
    "高级": [
        "当前基层工作中存在'上面千条线，下面一根针'的现象，你是怎么理解的？",
        "如果你被录用，但被分配到一个条件艰苦的基层岗位，你会接受吗？为什么？",
        "在一次重要会议上，你的观点被领导当众批评，气氛很尴尬，你怎么办？"
    ]
}


class InterviewCoach:
    """面试教练 - 提供练习指导和反馈"""

    def __init__(self):
        self.evaluator = InterviewEvaluator()

    def generate_practice_plan(self, focus_categories: List[str] = None) -> Dict:
        """生成练习计划"""
        if focus_categories is None:
            focus_categories = ["self_intro", "comprehensive", "emergency"]

        plan = {
            "categories": focus_categories,
            "daily_practice": [],
            "weekly_goals": [],
            "milestones": []
        }

        # 每日练习建议
        for category in focus_categories:
            suggestions = self.evaluator.get_practice_suggestions(category)
            plan["daily_practice"].append({
                "category": category,
                "tasks": suggestions[:2]  # 每天选2个任务
            })

        # 周目标
        plan["weekly_goals"] = [
            "完成至少10道面试题的练习",
            "录制并复盘3次面试回答",
            "背诵并熟练运用2个答题框架",
            "总结本周练习的心得体会"
        ]

        # 里程碑
        plan["milestones"] = [
            {"week": 1, "goal": "掌握基本答题框架，流畅度提升"},
            {"week": 2, "goal": "熟练掌握3类题型的答题方法"},
            {"week": 3, "goal": "形成个人答题风格，自信度提升"},
            {"week": 4, "goal": "能够应对各类题型，无明显短板"}
        ]

        return plan

    def get_weakness_improvement(self, evaluation_history: List[Dict]) -> Dict:
        """根据历史评价找出弱点并提供改进建议"""
        if not evaluation_history:
            return {"message": "暂无评价记录"}

        # 统计各维度平均分
        dimension_scores = {}
        for eval in evaluation_history:
            if "scores" in eval:
                for dim, score in eval["scores"].items():
                    if dim not in dimension_scores:
                        dimension_scores[dim] = []
                    dimension_scores[dim].append(score)

        avg_scores = {
            dim: sum(scores) / len(scores)
            for dim, scores in dimension_scores.items()
        }

        # 找出最低分的维度
        weakest_dim = min(avg_scores.items(), key=lambda x: x[1])

        # 针对性建议
        improvement_tips = {
            "逻辑性": [
                "学习并使用STAR法则（情境-任务-行动-结果）",
                "练习使用'首先、其次、最后'等连接词",
                "每道题先列出提纲再回答"
            ],
            "完整性": [
                "审题时圈出关键词，确保不遗漏要点",
                "练习多角度思考问题",
                "参考标准答案的要点结构"
            ],
            "针对性": [
                "练习快速识别题目类型和考点",
                "避免套话模板，根据题目调整内容",
                "多思考题目的实际意图"
            ],
            "深度": [
                "多关注社会热点和政策措施",
                "培养透过现象看本质的能力",
                "学习辩证思维，正反两方面分析"
            ],
            "表达": [
                "大声朗读练习，增强语感",
                "对着录音练习，回听检查",
                "控制语速，保持适中节奏"
            ]
        }

        return {
            "weakest_dimension": weakest_dim[0],
            "average_score": round(weakest_dim[1], 1),
            "improvement_tips": improvement_tips.get(weakest_dim[0], []),
            "all_scores": {k: round(v, 1) for k, v in avg_scores.items()}
        }


if __name__ == "__main__":
    # 测试
    coach = InterviewCoach()
    plan = coach.generate_practice_plan(["self_intro", "comprehensive"])

    print("=== 面试练习计划 ===")
    print(json.dumps(plan, ensure_ascii=False, indent=2))

    # 测试弱点分析
    history = [
        {"scores": {"逻辑性": 7, "完整性": 6, "针对性": 8, "深度": 5, "表达": 7}},
        {"scores": {"逻辑性": 6, "完整性": 5, "针对性": 7, "深度": 4, "表达": 6}},
        {"scores": {"逻辑性": 7, "完整性": 6, "针对性": 8, "深度": 5, "表达": 7}}
    ]

    analysis = coach.get_weakness_improvement(history)
    print("\n=== 弱点分析 ===")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))
