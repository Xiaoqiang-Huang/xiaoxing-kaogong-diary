"""
面试资料向量存储与RAG检索系统
使用ChromaDB实现轻量级本地向量数据库
"""
import os
import json
from typing import List, Dict, Optional
from datetime import datetime
import hashlib

# 文本分块与嵌入
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("警告: ChromaDB未安装，向量检索功能将不可用")
    print("安装命令: pip install chromadb")

# 文本嵌入（使用简单的方案，避免额外依赖）
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    print("提示: sentence-transformers未安装，将使用简单分词方案")
    print("安装命令: pip install sentence-transformers")


class SimpleEmbedder:
    """简单的文本嵌入器（使用词频向量）"""

    def __init__(self):
        self.vocab = set()
        self.documents = []

    def tokenize(self, text: str) -> List[str]:
        """简单的中文分词"""
        import re
        # 移除标点和特殊字符，按字符分词
        words = re.findall(r'[一-鿿]+|[a-zA-Z0-9]+', text.lower())
        return words

    def embed(self, text: str) -> List[float]:
        """生成文本嵌入向量"""
        words = self.tokenize(text)
        self.vocab.update(words)
        return self._to_vector(words)

    def _to_vector(self, words: List[str]) -> List[float]:
        """转换为向量（简化版）"""
        # 使用字符编码和位置信息生成固定长度向量
        vector = [0.0] * 512  # 固定512维
        for i, char in enumerate(words):
            # 使用字符的unicode值和位置生成特征
            idx = (sum(ord(c) for c in char) + i * 17) % 512
            vector[idx] += 1.0
        # 归一化
        total = sum(abs(v) for v in vector)
        if total > 0:
            vector = [v / total for v in vector]
        return vector

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量生成嵌入"""
        return [self.embed(text) for text in texts]


class InterviewKnowledgeBase:
    """面试知识库 - 向量存储与检索"""

    def __init__(self, persist_directory: str = "./data/chroma"):
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)

        # 初始化嵌入器
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            self.embedder = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            self.embedding_dim = 384
        else:
            self.embedder = SimpleEmbedder()
            self.embedding_dim = 512

        # 初始化ChromaDB
        if CHROMADB_AVAILABLE:
            self.client = chromadb.PersistentClient(path=persist_directory)
            self.collection = self.client.get_or_create_collection(
                name="interview_knowledge",
                metadata={"description": "面试教材知识库"}
            )
        else:
            self.client = None
            self.collection = None
            # 内存存储
            self._memory_store = {"ids": [], "documents": [], "embeddings": [], "metadatas": []}

    def add_document(self, content: str, metadata: Dict, doc_id: Optional[str] = None):
        """添加文档到知识库"""
        if not doc_id:
            doc_id = hashlib.md5(content.encode()).hexdigest()[:16]

        # 文本分块（每块约500字）
        chunks = self._chunk_text(content, chunk_size=500)
        chunk_ids = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            chunk_metadata = {
                **metadata,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "chunk_id": chunk_id
            }

            # 生成嵌入
            embedding = self.embedder.embed(chunk)

            if self.collection:
                # 使用ChromaDB
                self.collection.add(
                    ids=[chunk_id],
                    documents=[chunk],
                    embeddings=[embedding],
                    metadatas=[chunk_metadata]
                )
            else:
                # 内存存储
                self._memory_store["ids"].append(chunk_id)
                self._memory_store["documents"].append(chunk)
                self._memory_store["embeddings"].append(embedding)
                self._memory_store["metadatas"].append(chunk_metadata)

            chunk_ids.append(chunk_id)

        return chunk_ids

    def _chunk_text(self, text: str, chunk_size: int = 500) -> List[str]:
        """将文本分块"""
        import re

        # 按段落分割
        paragraphs = re.split(r'\n\n+', text)
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) <= chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"

                # 处理超长段落
                while len(current_chunk) > chunk_size:
                    chunks.append(current_chunk[:chunk_size])
                    current_chunk = current_chunk[chunk_size:]

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks if chunks else [text]

    def search(self, query: str, top_k: int = 3, filter_metadata: Optional[Dict] = None) -> List[Dict]:
        """检索相关文档"""
        query_embedding = self.embedder.embed(query)

        if self.collection:
            # 使用ChromaDB检索
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=filter_metadata
            )

            documents = []
            for i in range(len(results['ids'][0])):
                documents.append({
                    'id': results['ids'][0][i],
                    'content': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'distance': results['distances'][0][i] if 'distances' in results else 0
                })
            return documents
        else:
            # 内存检索（简单的余弦相似度）
            return self._memory_search(query_embedding, top_k, filter_metadata)

    def _memory_search(self, query_embedding: List[float], top_k: int, filter_metadata: Optional[Dict]) -> List[Dict]:
        """内存中的相似度搜索"""
        import math

        def cosine_similarity(a, b):
            dot_product = sum(x * y for x, y in zip(a, b))
            magnitude_a = math.sqrt(sum(x * x for x in a))
            magnitude_b = math.sqrt(sum(y * y for y in b))
            if magnitude_a == 0 or magnitude_b == 0:
                return 0
            return dot_product / (magnitude_a * magnitude_b)

        results = []
        for i, emb in enumerate(self._memory_store["embeddings"]):
            # 应用元数据过滤
            if filter_metadata:
                metadata = self._memory_store["metadatas"][i]
                if not all(metadata.get(k) == v for k, v in filter_metadata.items()):
                    continue

            similarity = cosine_similarity(query_embedding, emb)
            results.append({
                'id': self._memory_store["ids"][i],
                'content': self._memory_store["documents"][i],
                'metadata': self._memory_store["metadatas"][i],
                'distance': 1 - similarity  # 转换为距离
            })

        # 按相似度排序
        results.sort(key=lambda x: x['distance'])
        return results[:top_k]

    def get_context_for_question(self, question: str, category: str = "") -> str:
        """为面试问题获取相关上下文"""
        filter_dict = {"category": category} if category else None
        results = self.search(question, top_k=3, filter_metadata=filter_dict)

        if not results:
            return ""

        context_parts = []
        for result in results:
            source = result['metadata'].get('source', '资料')
            context_parts.append(f"【{source}】\n{result['content']}")

        return "\n\n".join(context_parts)

    def add_default_knowledge(self):
        """添加默认面试知识"""
        default_knowledge = [
            {
                "content": """
【公务员面试技巧 - 自我介绍】

自我介绍是公务员面试的重要环节，一般控制在2-3分钟。应包含以下要素：
1. 基本信息：姓名、年龄、学历、专业等
2. 教育背景：毕业院校、专业、学习成绩等
3. 实践经历：实习、工作、志愿服务等
4. 个人特质：性格特点、兴趣爱好等
5. 岗位认知：对报考岗位的理解
6. 匹配优势：为什么适合这个岗位

注意事项：
- 突出与岗位匹配的特质和经历
- 语言简洁明了，条理清晰
- 诚实真实，不夸大不虚构
- 展现积极向上的精神面貌
                """,
                "metadata": {"category": "self_intro", "source": "面试技巧库", "type": "技巧"}
            },
            {
                "content": """
【公务员面试技巧 - 综合分析题】

综合分析题考察考生对热点问题、社会现象、政策方针的理解和分析能力。

答题思路：
1. 表明态度：明确表达观点（支持/反对/辩证看待）
2. 分析原因：从多个角度分析问题产生的原因
3. 阐述影响：分析问题的积极/消极影响
4. 提出对策：针对问题提出解决方案
5. 总结提升：结合自身谈启示或做法

评分标准：
- 观点明确正确，立场坚定
- 分析全面深入，逻辑清晰
- 对策可行有效，符合实际
- 语言流畅，表达准确
                """,
                "metadata": {"category": "comprehensive", "source": "面试技巧库", "type": "技巧"}
            },
            {
                "content": """
【公务员面试技巧 - 应急应变题】

应急应变题考察考生在面对突发状况时的应变能力和处理问题的能力。

答题思路：
1. 快速反应：表明对问题的重视和及时处理的态度
2. 控制局面：采取紧急措施，防止事态扩大
3. 妥善处理：按照轻重缓急，有序解决问题
4. 总结反思：事后总结经验，完善机制

常见场景：
- 群众上访/闹事处理
- 突发事件应对
- 工作失误补救
- 媒体采访应对

评分要点：
- 反应迅速，措施得当
- 依法依规处理
- 以人为本，服务群众
- 注重长效，举一反三
                """,
                "metadata": {"category": "emergency", "source": "面试技巧库", "type": "技巧"}
            },
            {
                "content": """
【公务员面试技巧 - 人际关系题】

人际关系题考察考生在工作中处理人际关系的意识和能力。

答题原则：
1. 工作第一：以完成工作为目标
2. 尊重理解：尊重他人，理解不同立场
3. 主动沟通：积极沟通，化解矛盾
4. 团结协作：注重团队合作
5. 反思提升：总结经验，提升能力

常见关系处理：
- 与领导关系：尊重、服从、请示、汇报
- 与同事关系：团结、协作、互助、包容
- 与群众关系：热情、耐心、服务、便民
- 与下属关系：关心、指导、激励、信任

注意事项：
- 不直接批评同事或领导
- 不激化矛盾
- 体现大局意识和集体观念
                """,
                "metadata": {"category": "interpersonal", "source": "面试技巧库", "type": "技巧"}
            },
            {
                "content": """
【公务员面试技巧 - 组织协调题】

组织协调题考察考生策划、组织、协调的能力。

答题框架：
1. 准备阶段：
   - 调研了解：明确活动目的、内容、对象
   - 制定方案：包括时间、地点、人员、物资、预算等
   - 请示汇报：方案报领导审批

2. 实施阶段：
   - 人员分工：明确职责，责任到人
   - 协调沟通：与各方保持沟通
   - 进度控制：按计划推进
   - 应急准备：准备应急预案

3. 总结阶段：
   - 总结评估：活动效果评估
   - 宣传报道：扩大影响
   - 资料归档：做好记录
   - 反思改进：总结经验教训

常考活动：
- 会议组织、培训组织、考察调研
- 宣传活动、文体活动、志愿服务
- 应急演练、专项整治
                """,
                "metadata": {"category": "organization", "source": "面试技巧库", "type": "技巧"}
            }
        ]

        for item in default_knowledge:
            self.add_document(item["content"], item["metadata"])

    def get_stats(self) -> Dict:
        """获取知识库统计信息"""
        if self.collection:
            count = self.collection.count()
        else:
            count = len(self._memory_store["ids"])

        return {
            "total_documents": count,
            "embedding_dim": self.embedding_dim,
            "persist_directory": self.persist_directory,
            "chromadb_enabled": CHROMADB_AVAILABLE
        }


# 全局知识库实例
_knowledge_base = None

def get_knowledge_base() -> InterviewKnowledgeBase:
    """获取知识库单例"""
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = InterviewKnowledgeBase()
        # 添加默认知识
        _knowledge_base.add_default_knowledge()
    return _knowledge_base


if __name__ == "__main__":
    # 测试
    kb = get_knowledge_base()

    print("知识库统计:", kb.get_stats())

    # 测试检索
    query = "如何进行自我介绍"
    results = kb.search(query, top_k=2)

    print(f"\n查询: {query}")
    print("检索结果:")
    for i, result in enumerate(results, 1):
        print(f"\n{i}. [{result['metadata'].get('source', '未知')}]")
        print(f"内容: {result['content'][:100]}...")
        print(f"相似度: {1 - result['distance']:.2f}")
