# Local RAGPack

这个项目用于把中文 PDF/TXT 书籍批量构建成标准化的 `.rag.jsonl` RAG 数据包。

每本书会输出一个 JSONL 文件，文件内部包含：

- `manifest`：数据包版本、源文件 hash、解析参数、chunk 参数、embedding 模型信息
- `toc`：PDF 书签 / 目录结构
- `chunk`：正文分块、章节路径、前后 chunk 关系、hash、embedding

默认 embedding 模型：

```text
BAAI/bge-large-zh-v1.5
```

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

运行 `python main.py` 时，程序会先把 `raw_data/books` 根目录下的 PDF 自动分类并移动到对应文件夹，然后根据文件夹选择处理模式：

```text
raw_data/books/social_science  -> social_science 模式，社科/人文/通识类
raw_data/books/textbook        -> textbook 模式，教材/教辅/章节目结构资料
raw_data/books/technical       -> technical 模式，技术书/工程书/手册
raw_data/books/paper           -> paper 模式，论文/研究报告/白皮书
raw_data/books/legal           -> legal 模式，法律/政策/制度/标准
raw_data/books/english         -> english 模式，英文书
raw_data/books/fiction         -> fiction 模式，小说/叙事文学
raw_data/books/classical       -> classical 模式，古籍/传统文献
raw_data/books/reference       -> reference 模式，词典/百科/条目型资料
```

Markdown 输出规则：

```text
raw_data/markdown_files/journal            -> 按月份生成 journal_YYYY-MM.rag.jsonl
raw_data/markdown_files/TechNotes          -> 一个主题文件夹生成一个 .rag.jsonl
raw_data/markdown_files/WebPageCollection  -> 默认一篇网页 Markdown 生成一个 .rag.jsonl
```

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

输出文件写入：

```text
output/books_output/
output/markdown_output/
```

## 如何分类书籍

分类依据不是书籍学科，而是**目录和正文标题结构**。

### 放入 social_science 的书

适合目录层级较浅、章节标题偏叙述型的书。

典型结构：

```text
译序
前言
第一篇 阅读的层次
第一章 阅读的活力与艺术
第二章 阅读的层次
```

或：

```text
第3章 自我理解
监控日常思维和生活中的自我中心
努力做到思维公正
```

特征：

- 层级通常不深
- 多为“篇 / 章 / 主题小标题”
- 小标题可能没有严格编号
- 正文是连续论述，段落较长
- 不太常见 `一、`、`（一）`、`1.` 这种多级编号

适合例子：

```text
如何阅读一本书
批判性思维工具
一般社科、人文、哲学、心理、阅读方法类书籍
```

对应命令：

```powershell
python -m ragpack_builder build "如何阅读一本书_正式版.pdf" -o output --no-embedding
python -m ragpack_builder build "如何阅读一本书_正式版.pdf" -o output
```

### 放入 textbook 的书

适合目录结构规整、层级较多、明显是“章 / 节 / 条目”结构的书。

典型结构：

```text
第一章 总论
第一节 基本概念
一、研究对象
（一）基本定义
1. 主要特点
```

或：

```text
第一章 明朝覆亡后的全国形势
  第一节 明帝国的分崩离析
  第二节 大顺政权在政治上和军事上的失误
  第三节 吴三桂叛变与山海关之战
```

特征：

- 标题编号很规整
- 明显有“章 / 节”
- 可能继续细分为 `一、`、`（一）`、`1.`
- 更像教材、教辅、考试资料、专业资料、历史专著、制度性资料
- 如果用默认模式，可能会切得过粗或标题识别不够细

适合例子：

```text
南明史
教材
教辅
考试资料
技术手册
制度文件
结构规整的历史 / 法律 / 管理类资料
```

对应命令：

```powershell
python -m ragpack_builder build "南明史 - 顾诚.pdf" -o output --profile textbook --no-embedding
python -m ragpack_builder build "南明史 - 顾诚.pdf" -o output --profile textbook
```

### 放入 technical 的书

适合数字编号非常规整的技术书、工程书、产品手册、API 文档。

典型结构：

```text
1 Introduction
1.1 Background
1.1.1 Architecture
1.1.1.1 Components
```

或：

```text
1 系统概述
1.1 基本架构
1.1.1 模块说明
2 安装部署
```

特征：

- 标题主要是阿拉伯数字层级
- 常见 `1`、`1.1`、`1.1.1`
- 内容多为技术说明、配置、流程、接口、参数

对应命令：

```powershell
python -m ragpack_builder build "技术书.pdf" -o output --profile technical --no-embedding
python -m ragpack_builder build "技术书.pdf" -o output --profile technical
```

### 放入 paper 的书

适合论文、研究报告、咨询报告、白皮书。

典型结构：

```text
摘要
关键词
1 引言
2 文献综述
3 研究方法
3.1 数据来源
4 结果分析
参考文献
附录
```

特征：

- 有 `摘要`、`关键词`
- 正文常用 `1 引言`、`1.1 研究背景`
- 后面常有 `参考文献`、`附录`
- 章节结构比普通书更像研究报告

对应命令：

```powershell
python -m ragpack_builder build "论文.pdf" -o output --profile paper --no-embedding
python -m ragpack_builder build "论文.pdf" -o output --profile paper
```

### 放入 legal 的书

适合法律法规、政策文件、制度文件、标准规范。

典型结构：

```text
第一编 总则
第一章 基本原则
第一节 一般规定
第一条 立法目的
第二条 适用范围
```

特征：

- 常见 `编 / 章 / 节 / 条`
- `第X条` 本身就是重要检索单位
- 内容通常需要精确引用
- chunk 不宜过大

对应命令：

```powershell
python -m ragpack_builder build "法规.pdf" -o output --profile legal --no-embedding
python -m ragpack_builder build "法规.pdf" -o output --profile legal
```

### 放入 english 的书

适合英文书或英文资料。

典型结构：

```text
Part I Foundations
Chapter 1 Introduction
1.1 Background
1.1.1 Prior Work
Appendix A Resources
Bibliography
```

特征：

- 常见 `Part`、`Chapter`、`Appendix`
- 也可能有 `1.1`、`1.1.1` 数字层级
- 段落长度通常比中文更长

对应命令：

```powershell
python -m ragpack_builder build "english-book.pdf" -o output --profile english --no-embedding
python -m ragpack_builder build "english-book.pdf" -o output --profile english
```

### 放入 fiction 的书

适合小说、故事集、叙事文学。

典型结构：

```text
楔子
第一章 风起
第二章 夜行
第三章 重逢
尾声
番外
```

或：

```text
Chapter 1
Chapter 2
Epilogue
```

特征：

- 章节通常按 `第X章`、`第X回`、`Chapter X` 排列
- 层级较浅
- 正文强调叙事连续性
- chunk 可以比普通社科书略大，overlap 也略大

对应命令：

```powershell
python -m ragpack_builder build "小说.pdf" -o output --profile fiction --no-embedding
python -m ragpack_builder build "小说.pdf" -o output --profile fiction
```

### 放入 classical 的书

适合古籍、传统文献、史籍、文集、经史子集类材料。

典型结构：

```text
卷一
卷二
上篇
下篇
本纪
世家
列传
某某传
```

特征：

- 常见 `卷一`、`卷上`、`上篇`、`下篇`
- 常见 `本纪`、`世家`、`列传`、`志`、`表`
- 人物条目可能是 `某某传`
- 适合传统史籍、古文集、注疏类资料

对应命令：

```powershell
python -m ragpack_builder build "古籍.pdf" -o output --profile classical --no-embedding
python -m ragpack_builder build "古籍.pdf" -o output --profile classical
```

### 放入 reference 的书

适合词典、辞典、百科、术语表、索引、条目型资料。

典型结构：

```text
A
Algorithm
Anomaly Detection
B
Bayes Theorem
```

或：

```text
系统
系统边界
系统工程
复杂系统
```

特征：

- 不是连续章节型，而是大量独立条目
- 每个条目通常较短
- 可能按字母、拼音、部首、主题分类
- 检索时更需要精确命中词条

对应命令：

```powershell
python -m ragpack_builder build "百科.pdf" -o output --profile reference --no-embedding
python -m ragpack_builder build "百科.pdf" -o output --profile reference
```

## 不确定怎么分类时

优先看 PDF 左侧书签 / 目录。

如果目录像这样：

```text
第一篇
第一章
第二章
第三章
```

通常放入：

```text
raw_data/books/social_science
```

如果目录像这样：

```text
第一章
  第一节
  第二节
  第三节
```

通常放入：

```text
raw_data/books/textbook
```

如果目录继续出现：

```text
一、
（一）
1.
1.1
```

应放入：

```text
raw_data/books/textbook
```

如果目录主要是：

```text
1
1.1
1.1.1
```

并且内容是技术、工程、软件、产品说明，放入：

```text
raw_data/books/technical
```

如果开头有：

```text
摘要
关键词
1 引言
参考文献
```

放入：

```text
raw_data/books/paper
```

如果结构是：

```text
第X编
第X章
第X节
第X条
```

放入：

```text
raw_data/books/legal
```

如果是英文书，且出现：

```text
Part
Chapter
Appendix
Bibliography
```

放入：

```text
raw_data/books/english
```

如果是小说或叙事文学，目录主要是：

```text
第一章
第二章
第三章
尾声
番外
```

放入：

```text
raw_data/books/fiction
```

如果是古籍或传统文献，目录主要是：

```text
卷一
卷二
本纪
列传
某某传
```

放入：

```text
raw_data/books/classical
```

如果是词典、百科、索引、术语表，目录主要是大量词条：

```text
A
Algorithm
Bayes Theorem
系统
系统边界
系统工程
```

放入：

```text
raw_data/books/reference
```

如果一本书是社科/人文主题，但目录结构明显是“章 / 节”型，也应该放入 `textbook`。  
例如《南明史》是历史社科类书，但它的目录是严格的“章 / 节”结构，因此使用 `textbook` 模式更合适。

## 批量处理

把书放好后，直接运行：

```powershell
python main.py
```

程序会自动处理：

```text
1. 检测 raw_data/books 根目录下尚未分类的 PDF
2. 根据 PDF 书签和前若干页文本自动判断分类
3. 把 PDF 移动到 raw_data/books/<分类>/ 目录
4. 扫描 raw_data/books/<分类>/ 里的 PDF/TXT
5. 生成 output/books_output/书名.rag.jsonl
6. 扫描 raw_data/markdown_files 下的 Markdown
7. 生成 output/markdown_output/*.rag.jsonl
```

先生成不带 embedding 的调试版：

```powershell
python main.py --no-embedding
```

调试版文件名：

```text
书名_noembedding.rag.jsonl
```

正式 embedding 版文件名：

```text
书名.rag.jsonl
```

书籍输出目录：

```text
output/books_output/
```

Markdown 输出目录：

```text
output/markdown_output/
```

## Markdown 资料处理

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

## 预览自动分类结果

`python main.py` 默认会自动分类并继续构建。如果你不确定分类是否合适，可以先把 PDF 放在 `raw_data/books` 根目录下：

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
```

然后只预览分类结果，不移动文件：

```powershell
python main.py classify --dry-run
```

确认无误后有两种选择。

只执行分类移动：

```powershell
python main.py classify
```

或者直接执行完整流程：

```powershell
python main.py
```

程序会根据 PDF 书签和前若干页文本中的结构信号自动判断分类，把 PDF 移动到对应文件夹，然后继续生成 `.rag.jsonl`。

判断信号包括：

```text
social_science：译序、前言、导论、篇/章/主题小标题
textbook：第一章、第一节、一、（一）等章节目结构
technical：1、1.1、1.1.1、API、配置、架构、模块等
paper：摘要、关键词、1 引言、参考文献
legal：第X编、第X章、第X节、第X条、条例、办法、规定
english：Part、Chapter、Appendix、英文文本比例较高
fiction：第X章、第X回、楔子、尾声、番外、小说叙事信号
classical：卷X、本纪、世家、列传、志、表、某某传
reference：词典、百科、Glossary、Dictionary、大量短词条
```

示例输出：

```text
would move: 某本书.pdf -> raw_data/books/textbook/某本书.pdf
  scores: textbook=6, social_science=2, english=0, legal=0, paper=0, technical=0
  signals:
    textbook+6: detected 章/节 structure
```

如果分类结果不满意，可以手动把 PDF 移动到你认为更合适的文件夹。自动分类只是辅助判断，不会影响已经放在分类子文件夹里的书。

## 单本书调试

保留单本书命令，方便测试某本书的解析效果。

默认 social_science 模式：

```powershell
python -m ragpack_builder build "书名.pdf" -o output --no-embedding
python -m ragpack_builder build "书名.pdf" -o output
```

textbook 模式：

```powershell
python -m ragpack_builder build "书名.pdf" -o output --profile textbook --no-embedding
python -m ragpack_builder build "书名.pdf" -o output --profile textbook
```

## textbook 模式的分块层级

textbook 模式默认参数：

```text
target_chars = 700
max_chars = 1100
section_split_chars = 2000
min_chunk_chars = 180
overlap_chars = 80
max_chunk_heading_level = 4
```

当前分块策略是 `section-first chunking`：

```text
1. 优先尊重目录 / 标题 / 小节边界
2. 一个自然小节不超过 section_split_chars 时，尽量整节保留为一个 chunk
3. 小节太短时，和相邻同级小节合并
4. 小节超过 section_split_chars 时，才按段落 / 句子二次切分
5. max_chars 控制二次切分后的单片大小，不再表示所有 chunk 的硬上限
```

这样设计的原因是：一本书里的“小节”通常是作者已经划分好的天然语义单元。一个小节往往围绕一个概念、一个论点、一个步骤或一个案例展开，直接保留为 chunk，语义纯度通常比按固定 700 或 1100 字硬切更高，也更适合后续向量检索和问答引用。

程序现在采用的是“先按结构，后按长度”的策略：

```text
书籍 chunking 优先级
├─ 1. 优先使用 PDF 书签 / 目录结构
│  ├─ 章节、小节、三级标题会成为主要 chunk 边界
│  └─ 父级章节的导言文字会被保留，不会因为存在子标题而丢失
├─ 2. 修复乱码目录
│  ├─ 如果 PDF 左侧书签标题乱码
│  ├─ 程序会尝试从正文前几页的目录文本中寻找干净标题
│  └─ 能匹配时，用正文目录标题替换乱码书签标题
├─ 3. 正文短标题增强
│  ├─ 当 PDF 书签层级较浅，但正文中存在独立短标题时启用
│  ├─ 例如《如何阅读一本书》的“书籍分类的重要性”
│  ├─ 这些短标题会被补充成更细的结构边界
│  └─ 如果 PDF 书签本身已经很细，则通常不会额外增强
├─ 4. 小节优先保留
│  ├─ 小节长度 <= section_split_chars：整节保留为一个 chunk
│  ├─ 小节太短：和相邻同级小节合并
│  └─ 小节太长：再按段落 / 句子二次切分
└─ 5. 输出可迁移 RAGPack
   ├─ chunk.text 保留原始正文
   ├─ embedding_text 带书名、标题路径和正文
   ├─ heading_path 保留引用路径
   └─ prev_chunk_id / next_chunk_id 保留前后关系
```

正文短标题增强不是无条件启用的。程序会尽量保守地判断“这一行是不是标题”，主要依据包括：

```text
1. 单独成行
2. 长度适中，通常不是完整长句
3. 不以明显句号、问号、引号残片等正文标点结尾
4. 不像普通段落、注释、页码、纯英文残片
5. 出现在可增强的章节范围内
6. 与已有 PDF 书签结构不冲突
```

因此，像《批判性思维工具》这种 PDF 书签本身已经包含大量三级标题的书，通常会主要依赖原始书签；像《如何阅读一本书》这种书签较浅、正文中存在许多清晰短标题的书，则会补充正文短标题，让 chunk 更接近真实语义小节。

对于下面这种层级：

```text
第一章 总论          level 1
第一节 基本概念      level 2
一、研究对象         level 3
（一）基本定义       level 4
1. 主要特点          level 5
```

默认最多按第 4 级 `（一）基本定义` 分块，`1. 主要特点` 会保留在父级 chunk 正文里，避免切得太碎。

如果你希望切到 `1. 主要特点` 这一层，可以使用：

```powershell
python -m ragpack_builder build "教材.pdf" -o output --profile textbook --max-chunk-heading-level 5
```

批量模式也可以覆盖 textbook 的最细分块层级：

```powershell
python main.py --max-chunk-heading-level 5
```

## 安装依赖

处理 PDF 和 embedding：

```powershell
pip install -e .[pdf]
```

如果只处理 TXT：

```powershell
pip install -e .
```

第一次正式生成 embedding 时，`sentence-transformers` 会下载模型，请确保网络和缓存目录可用。

## 推荐工作流

1. 把 PDF 放入 `raw_data/books` 根目录，或手动放入 `raw_data/books/<分类>` 目录
2. 如果不确定分类，可以先运行：

```powershell
python main.py classify --dry-run
```

3. 先生成不带 embedding 的调试版：

```powershell
python main.py --no-embedding
```

4. 抽查 `output/books_output/书名_noembedding.rag.jsonl` 或 `output/markdown_output/*_noembedding.rag.jsonl`
5. 确认标题、chunk 边界正常
6. 再运行：

```powershell
python main.py
```

7. 保存正式的 `output/books_output/书名.rag.jsonl` 和 `output/markdown_output/*.rag.jsonl`
