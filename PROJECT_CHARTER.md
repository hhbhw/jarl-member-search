# JARL Member Search — 项目准则

> 本文件是项目的"宪法"。每次修改代码前，对照这里的目标、范围、非目标和约束。
> **如果一项改动不符合本准则，要么改准则（先和用户确认），要么不做。** 不做"顺手优化"。

---

## 1. 项目目标（One-liner）

**输入一批业余无线电呼号，自动筛出日本呼号，查询 JARL 官网，输出哪些是 JARL 会员。**

支持三种输入：手动粘贴、ADI/ADIF 文件、QRZ Logbook API。
输出：本地 Web UI 表格 + CSV 导出。

---

## 2. 用户与场景

- **用户**：业余无线电爱好者，主要是本项目所有者（justbepositive22172@gmail.com）
- **典型场景**：扫描自己日志里和日本电台的 QSO，找出可以申请 JARL 相关奖项 / 交换卡片的会员对象
- **频次**：偶尔批量扫描一次几百到几千个呼号，不是高频实时查询
- **使用环境**：本地 macOS，浏览器 + 终端

---

## 3. 范围（In Scope）

### 3.1 MVP 必须包含
1. **本地 Web UI**（Flask 或 FastAPI + 简单 HTML 前端，单端口本地访问）
2. **三种输入方式**：
   - 手动粘贴呼号列表（每行一个）
   - 上传 ADI/ADIF 文件，解析提取 `CALL` 字段
   - 输入 QRZ Logbook API key，按时间范围拉取
3. **日本呼号筛选**：
   - 接受前缀：`JA JE JF JG JH JI JJ JK JL JM JN JO JP JQ JR JS 7J 7K 7L 7M 7N 8J 8N`
   - 去除后缀：自动剥离 `/数字`、`/P`、`/M`、`/MM`、`/AM`、`/QRP` 等，只查主呼号
4. **JARL 查询**（v0.1 技术验证已确认）：
   - 查询入口：https://www.jarl.com/Page/Search/MemberSearch.aspx?Language=Jp
   - **方案**：`httpx` 直接 POST 标准 ASP.NET WebForms（已验证可行，无需 Playwright）
   - 必带字段：`__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`, `hdnMemberType=Jp`, `txtCallSign`, `btnSearch=検　索`
   - **批量利用**：JARL 表单原生支持半角空格分隔最多 20 个呼号/次。我们的请求按 20 一批打包
   - 限速：默认 1 req/s（一批 20 个），重试 3 次指数退避，**不并发**
   - **JARL 返回 5 种结果字符串**，全部要识别：
     - `○ Yes` / `○ YES` → 会员 + 可转 QSL
     - `○ No` / `○ NO` → 会员 + 不可转 QSL
     - `×` → 非会员（或会员但拒绝公开）—— Charter 把这归类为 `no`
     - `○ Yes via {callsign}` → 会员，借用其他呼号转 QSL
     - `○ YES **/{callsign}/** via {callsign}` → 会员，海外运行
   - 解析：从响应 HTML 提取 `ListView1_lblCallSign_N` 和 `ListView1_lblResult_N` 配对
5. **本地缓存**（SQLite）：
   - 表结构至少包含：`callsign, is_member, name, qth, queried_at, raw_html_or_json`
   - 查询前先看缓存，命中则跳过
   - 缓存有效期：默认 30 天（可在配置里改）
6. **流式实时结果**：Web UI 不等待全部 JARL 查询完成，每批（≤20 个）查完立刻把结果追加到表格里
   - 实现：服务端 NDJSON 流（`event: start | result | done | error` 行），前端用 `fetch` + `ReadableStream` reader 解析并 append 行
   - 显示 `已查 X/Y，会员 N 人` 的进度条；缓存命中的结果在 `start` 后立刻 flush，无需走 JARL
7. **结果筛选/排序**：表格可按"仅会员"、"按 QTH"等过滤
8. **CSV 导出**：列 = `callsign, is_jarl_member, qsl_via, raw_result, queried_at`
   - ⚠️ **JARL 不返回姓名 / QTH**（v0.1 技术验证已确认，原假设是错的）
   - `is_jarl_member` 三态：`yes` / `no` / `unknown`
     - `yes` ← `○ Yes`, `○ No`, `○ Yes via ...`（注意：JARL 的 `○ No` 仍是会员，只是不能转 QSL）
     - `no` ← `×`
     - `unknown` ← 网络失败 / HTML 结构变化 / 解析失败
   - `qsl_via` ← 从 `○ Yes via {callsign}` 类型结果里抽取的代理呼号；其他情况留空
   - `raw_result` ← 原始 JARL 字符串（`○ Yes` / `○ No` / `×` / 等），便于调试
   - **`unknown` 在 UI 里必须高亮**，提示用户去浏览器手动核对——不要把网络问题当成"非会员"
9. **QRZ API key 隔离**：`.env` + `.gitignore` + 提交前自检脚本，**绝不进 git**
10. **ADI 成员过滤导出**（输入是 ADI 时启用）：导出一份只包含会员 QSO 的 ADI 文件
    - 保留原 QSO 的全部字段（QSO_DATE / TIME_ON / BAND / MODE / RST 等）
    - 不修改、不添加字段；纯粹按 CALL 字段过滤，保留 ADI 头
    - 只保留 `is_jarl_member == 'yes'` 的记录。`unknown` 不保留（避免污染），UI 文案要说明
    - 按字节级保留原记录文本，不重新序列化——防止 ADIF 兼容性回退

### 3.2 验证标准（"完成"的定义）
任何 release 必须通过：
- **正例**：`JA1RL`（JARL 本部台）等已知会员呼号查询结果为"会员"
- **反例**：`BG7XXX`、`ZZZ123` 等被正确筛掉或标为非会员
- **端到端**：从 QRZ 拉取真实日志 → 筛选 → 查询 → 导出 CSV，全流程跑通无人工干预
- **可复现**：Playwright 脚本（若启用）能在重启后无需重装环境直接跑

---

## 4. 非目标（Out of Scope — 不要在 MVP 里做）

显式排除，避免范围蔓延。这些是好想法，但**不属于当前迭代**：

- ❌ 给 ADI 的 QSO **添加新字段**（如 `APP_JARL_MEMBER`）——只允许"过滤", 不允许"标注"
- ❌ 桌面 GUI（Tkinter/PyQt）
- ❌ 浏览器扩展
- ❌ 并发查询（与限速冲突，且对 JARL 不友好）
- ❌ 自动发卡片 / 邮件提醒 / 任何对外发起的动作
- ❌ 用户登录、多用户、权限系统
- ❌ Docker / Kubernetes / 云部署
- ❌ 实时 WebSocket（HTTP 轮询足够）
- ❌ 国际化（中/日/英多语言界面）—— 单语界面即可

**如果想加这些，先开 issue，更新本准则的"范围"章节，再动手。**

---

## 5. 技术约束

- **语言**：Python 3.11+
- **后端框架**：FastAPI（异步友好，自动生成 OpenAPI 文档便于自测）
- **前端**：服务器渲染 HTML + 少量 vanilla JS / HTMX，**不引入 React/Vue 等前端框架**
- **持久化**：SQLite，单文件，跟代码放一起
- **JARL 抓取**：先 `httpx`，必要时 Playwright（chromium）
- **ADI 解析**：自己写最小解析器（ADIF 格式简单），不引入重型库
- **依赖管理**：`requirements.txt`（保持精简），不引入 Poetry/PDM 等
- **测试框架**：pytest
- **代码风格**：遵循 PEP 8，不强制 black/ruff（但欢迎）

---

## 6. 安全与隐私准则（硬约束）

- 🔒 **任何 API key、密码、token 永远不进 git**。`.env.example` 给占位符，真实 `.env` 加入 `.gitignore`
- 🔒 提交前必须运行 `scripts/check_secrets.sh`（grep 几个常见前缀），出现疑似 key 直接拒绝
- 🔒 用户提供的 QRZ key（XXXX-XXXX-XXXX-XXXX 形式）仅用于本地测试，**永不出现在任何提交的文件、日志、commit message、PR 描述中**
- 🔒 SQLite 缓存放在 `data/` 目录，加入 `.gitignore`，避免泄露日志数据
- 🔒 JARL 查询遵守限速，不对官网造成异常负载

---

## 7. 工程准则（每次改动都要遵守）

1. **目标对齐**：动手前问自己——这个改动属于第 3 节哪一项？不属于就别做。
2. **最小改动**：bug fix 不顺手重构；新增功能不顺手"美化"无关代码。
3. **不要预设未来**：不为假想需求加抽象层、配置项、插件机制。
4. **不要静默回退/隐藏错误**：JARL 查不到结果 ≠ "非会员"，要区分"未查到"和"确认非会员"。
5. **缓存不撒谎**：写缓存前确认是真实结果，不要把错误状态当结果存。**`unknown` 绝不进缓存**——下次必须重查，否则等于把"我们不知道"锁死 30 天。
6. **不擅自扩范围**：发现"顺手能做的好事"？写进 ROADMAP 备选，不写进当前 PR。
7. **可复现优先**：所有依赖、环境变量、初始化步骤写进 README。

---

## 8. 测试与验证准则

- 单测：呼号筛选规则、ADI 解析、缓存读写
- 集成测试：用 `JA1RL` 等已知呼号跑一次真实 JARL 查询（可手动触发，不进 CI）
- E2E：手动跑一次 QRZ → 筛选 → JARL → CSV，记录截图存 `docs/verification/`
- **每次发版前必须重跑 §3.2 的三条验证标准**

---

## 9. 仓库与协作

- GitHub repo：**Public**，名字建议 `jarl-member-search`
- 分支策略：`main` 主分支，feature 用短命名分支（个人项目，不强制 PR）
- README 必须包含：安装步骤、运行步骤、QRZ key 配置说明、JARL 限速说明
- License：MIT（个人工具，开放使用）

---

## 10. 偏离本准则的流程

如果你（或未来的 AI 助手）想做本准则没覆盖或明确排除的事：

1. 停下来，写一段话说明：想做什么、为什么、影响哪些章节
2. 询问用户确认
3. 用户同意后，**先更新本准则**，再写代码
4. commit message 里引用本准则章节号（例如 "Scope §3.1 extended: add ADI write-back"）

**不要先斩后奏。**
