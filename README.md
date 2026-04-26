# Local RAGPack

Local RAGPack 用于把书籍 PDF/TXT 和 Markdown 资料构建成标准化、可迁移的 `.rag.jsonl` RAG 数据包。

目标是：以后导入个人知识库、换知识库软件、换向量库时，尽量不需要重新解析、重新切分、重新生成向量。

每个 RAGPack 文件包含：

- `manifest`：数据包版本、源文件 hash、解析参数、chunk 参数、embedding 模型信息
- `toc`：目录 / 书签 / 标题结构
- `chunk`：正文分块、标题路径、前后 chunk 关系、hash、embedding

默认 embedding 模型：

```text
BAAI/bge-large-zh-v1.5
```

## 安装

处理 PDF 和 embedding：

```powershell
pip install -e .[pdf]
```

如果只处理 TXT：

```powershell
pip install -e .
```

第一次正式生成 embedding 时，`sentence-transformers` 会下载模型，请确保网络和缓存目录可用。

## 目录结构

原始资料分成两条管线：书籍放入 `raw_data/books`，Markdown 资料放入 `raw_data/markdown_files`。

```text
raw_data/
  books/
    某本书.pdf
    social_science/
    textbook/
    technical/
    paper/
    legal/
    english/
    fiction/
    classical/
    reference/
  markdown_files/
    journal/
    TechNotes/
    WebPageCollection/
output/
  books_output/
  markdown_output/
```

输出文件：

```text
output/books_output/书名_noembedding.rag.jsonl
output/books_output/书名.rag.jsonl
output/markdown_output/*.rag.jsonl
```

## 快速开始

推荐的两步流程：

```powershell
python main.py preflight
python main.py build
```

`preflight` 会先生成 no-embedding 调试文件，然后对书籍 PDF 的 no-embedding 文件进行自检：

```text
python main.py preflight
  = python main.py build --no-embedding
  + python main.py inspect --all
```

正式生成 embedding：

```text
python main.py build
  = 生成正式 embedding 版 .rag.jsonl
```

也可以一步执行完整流程：

```powershell
python main.py
```

`python main.py` 会先执行 `preflight`。只有 preflight 没有 `FAIL`，才会继续执行正式 embedding 构建；如果 preflight 失败，程序会打印建议并停止。

## 工作流

1. 把 PDF 放入 `raw_data/books` 根目录，或手动放入 `raw_data/books/<分类>` 目录
2. 把日记、技术笔记、网页收藏放入 `raw_data/markdown_files` 对应目录
3. 不确定书籍分类时，先运行：

```powershell
python main.py classify --dry-run
```

4. 执行预检：

```powershell
python main.py preflight
```

5. 如果全部 `PASS`，生成正式 embedding：

```powershell
python main.py build
```

6. 如果有 `WARN`，建议先打开 `output/books_output/*.inspect.html` 抽查
7. 如果有 `FAIL`，先根据报告建议修复，再重新运行 `python main.py preflight`

## 书籍分类

分类依据不是书籍学科，而是**目录和正文标题结构**。如果一本书是社科/人文主题，但目录结构明显是“章 / 节”型，也应该放入 `textbook`。

| 文件夹 | 适合资料 | 典型结构 |
| --- | --- | --- |
| `social_science` | 社科、人文、哲学、心理、阅读方法、通识类 | `第一篇` / `第一章` / 主题小标题 |
| `textbook` | 教材、教辅、考试资料、结构规整的历史/管理/专业资料 | `第一章` / `第一节` / `一、` / `（一）` |
| `technical` | 技术书、工程书、产品手册、API 文档 | `1` / `1.1` / `1.1.1` |
| `paper` | 论文、研究报告、咨询报告、白皮书 | `摘要` / `关键词` / `1 引言` / `参考文献` |
| `legal` | 法律法规、政策文件、制度文件、标准规范 | `第X编` / `第X章` / `第X节` / `第X条` |
| `english` | 英文书或英文资料 | `Part` / `Chapter` / `Appendix` |
| `fiction` | 小说、故事集、叙事文学 | `楔子` / `第一章` / `尾声` / `番外` |
| `classical` | 古籍、传统文献、史籍、文集 | `卷一` / `本纪` / `世家` / `列传` |
| `reference` | 词典、百科、术语表、索引、条目型资料 | 大量短词条、字母索引、主题条目 |

示例：

```text
《如何阅读一本书》       -> social_science
《批判性思维工具》       -> social_science
《南明史》               -> textbook
技术手册 / API 文档      -> technical
法律法规 / 政策文件      -> legal
词典 / 百科 / 术语表     -> reference
```

自动分类预览：

```powershell
python main.py classify --dry-run
```

执行分类移动：

```powershell
python main.py classify
```

自动分类只处理直接放在 `raw_data/books` 根目录下的 PDF；已经放入分类子文件夹的书不会被移动。

## Markdown 资料

Markdown 资料统一放在：

```text
raw_data/markdown_files/
```

当前支持三类：

```text
journal            日记
TechNotes          技术笔记
WebPageCollection  保存的网页内容
```

### journal

日记文件放入：

```text
raw_data/markdown_files/journal/
```

文件名建议使用日期：

```text
2026-04-25.md
2026-04-26.md
```

程序会按月份聚合：

```text
output/markdown_output/journal_2026-04.rag.jsonl
```

日期 metadata 优先从文件名提取 `logical_date`。

### TechNotes

技术笔记按主题文件夹聚合：

```text
raw_data/markdown_files/TechNotes/
  RAG技术学习/
    1. 文档预处理与分块（Chunking）.md
    2. 向量嵌入（Embedding）.md
```

输出：

```text
output/markdown_output/RAG技术学习.rag.jsonl
```

如果 `TechNotes` 下直接放单个 `.md` 文件，该文件会作为一个独立主题包输出。

### WebPageCollection

网页收藏默认一篇 Markdown 输出一个 RAGPack：

```text
raw_data/markdown_files/WebPageCollection/
  Milvus HNSW 参数解释.md
```

输出：

```text
output/markdown_output/Milvus HNSW 参数解释.rag.jsonl
```

### Markdown 日期 metadata

Markdown chunk 会记录源文件日期 metadata，方便未来按日期回顾：

```text
source.markdown_profile
source.file_name
source.file_path
source.file_created_at
source.file_modified_at
source.front_matter_date
source.logical_date
source.logical_month
```

日期优先级：

```text
journal：优先从文件名 2026-04-10.md 提取 logical_date
TechNotes / WebPageCollection：优先读取 Markdown front matter 中的 created/date/saved_at 等字段
没有显式日期时：使用文件修改日期
```

## Chunking 算法

当前书籍分块策略是 `section-first chunking`：优先尊重书籍自身的目录、标题、小节边界。

核心规则：

```text
1. 优先使用 PDF 书签 / 目录结构
2. 修复 PDF 书签中的乱码目录标题
3. 当书签层级较浅时，尝试正文短标题增强
4. 一个自然小节不超过 section_split_chars 时，尽量整节保留为一个 chunk
5. 小节太短时，和相邻同级小节合并
6. 小节超过 section_split_chars 时，才按段落 / 句子二次切分
7. max_chars 控制二次切分后的单片大小，不再表示所有 chunk 的硬上限
```

这样设计的原因是：一本书里的“小节”通常是作者已经划分好的天然语义单元。一个小节往往围绕一个概念、一个论点、一个步骤或一个案例展开，直接保留为 chunk，语义纯度通常比按固定字数硬切更高，也更适合后续向量检索和问答引用。

正文短标题增强不是无条件启用的。程序会保守判断“这一行是不是标题”，主要依据包括：

```text
1. 单独成行
2. 长度适中，通常不是完整长句
3. 不以明显句号、问号、引号残片等正文标点结尾
4. 不像普通段落、注释、页码、纯英文残片
5. 出现在可增强的章节范围内
6. 与已有 PDF 书签结构不冲突
```

例如：

```text
《批判性思维工具》：PDF 书签本身已经很细，通常主要依赖原始书签。
《如何阅读一本书》：书签较浅、正文短标题清晰，会补充正文短标题。
```

### textbook 层级控制

textbook 模式默认参数：

```text
target_chars = 700
max_chars = 1100
section_split_chars = 2000
min_chunk_chars = 180
overlap_chars = 80
max_chunk_heading_level = 4
```

对于下面这种层级：

```text
第一章 总论          level 1
第一节 基本概念      level 2
一、研究对象         level 3
（一）基本定义       level 4
1. 主要特点          level 5
```

默认最多按第 4 级 `（一）基本定义` 分块，`1. 主要特点` 会保留在父级 chunk 正文里，避免切得太碎。

如果希望切到 `1. 主要特点` 这一层：

```powershell
python main.py preflight --max-chunk-heading-level 5
python main.py build --max-chunk-heading-level 5
```

单本书调试：

```powershell
python -m ragpack_builder build "教材.pdf" -o output --profile textbook --max-chunk-heading-level 5
```

## 自检功能

`preflight` 会自动完成 no-embedding 构建和书籍自检：

```powershell
python main.py preflight
```

也可以单独运行自检：

```powershell
python main.py inspect "raw_data/books/social_science/书名.pdf" "output/books_output/书名_noembedding.rag.jsonl"
python main.py inspect --all
```

自检结果分为三档：

```text
PASS  可以继续生成 embedding
WARN  基本可用，但建议先人工抽查
FAIL  不建议继续，应先检查 PDF、分类或 chunking 参数
```

自检会检查：

```text
1. PDF 文件和 RAGPack manifest 是否匹配
2. manifest / toc / chunk schema 是否完整
3. chunk 长度分布是否健康
4. heading_path 是否过浅、为空或过度集中
5. 目录、heading_path、chunk 正文是否存在疑似乱码
6. chunk 文本和 PDF 文本的覆盖关系是否异常
7. profile 与 chunking 参数是否一致
8. 是否确认为 no-embedding 文件
```

自检还会生成本地离线建议：

```text
1. 抽样对照 PDF 页面和 chunk 正文
2. 自动推荐是否需要调整 profile
3. 自动推荐是否需要调整 --max-chunk-heading-level
4. 自动推荐是否需要开启 / 保持正文短标题增强
5. 生成 HTML 可视化报告
```

默认报告：

```text
output/books_output/书名_noembedding.rag.inspect.json
output/books_output/书名_noembedding.rag.inspect.html
```

只看终端、不写报告：

```powershell
python main.py inspect --all --no-report
```

当前 `preflight` 只对书籍 PDF 做 inspect。Markdown 资料会生成 no-embedding 调试版，但暂时不做类似 PDF 的对照自检。

## 命令参考

批量预检：

```powershell
python main.py preflight
```

批量正式构建：

```powershell
python main.py build
```

一步完成预检和构建：

```powershell
python main.py
```

只生成 no-embedding：

```powershell
python main.py build --no-embedding
```

分类预览：

```powershell
python main.py classify --dry-run
```

单本书调试：

```powershell
python -m ragpack_builder build "书名.pdf" -o output --no-embedding
python -m ragpack_builder build "书名.pdf" -o output
python -m ragpack_builder build "书名.pdf" -o output --profile textbook --no-embedding
python -m ragpack_builder inspect "书名.pdf" "书名_noembedding.rag.jsonl"
```

## 后续任务

- 为 Markdown RAGPack 设计专门的自检规则，而不是沿用 PDF 页面级对照逻辑
- 在 inspect 报告里加入更丰富的 Markdown 统计，例如日期覆盖、文件聚合关系、标题层级分布
- 继续优化 profile 自动推荐，降低低置信度场景下的误导性
- 增加 HTML 报告中的可视化图表，例如 chunk 长度直方图、标题层级分布图
- 增加更多真实书籍样本测试，覆盖教材、法律、词典、小说、英文书等类别
