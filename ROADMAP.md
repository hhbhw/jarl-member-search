# 项目迭代方案 / Roadmap

> 阅读顺序：先读 `PROJECT_CHARTER.md`，再看本文件。
> 本文件只列**做什么、什么顺序**，不解释为什么——动机在 Charter 里。

---

## 迭代节奏

按"垂直切片"推进——每个迭代都能跑通端到端，不存在"先搭半个框架"的阶段。

---

## v0.1 — 骨架可跑（最快验证 JARL 抓取）

**目标**：手动粘贴一个呼号，能查到 JARL 结果。
**完成定义**：`JA1RL` 在 Web UI 上显示为会员。

- [ ] 项目结构搭好：`app/`, `data/`, `tests/`, `scripts/`
- [ ] `requirements.txt`：fastapi, uvicorn, httpx, jinja2, python-multipart, python-dotenv, beautifulsoup4
- [ ] `.gitignore`：`.env`, `data/`, `__pycache__/`, `.venv/`, `*.adi`（防误传日志）
- [ ] `.env.example`：占位 `QRZ_API_KEY=your_key_here`
- [ ] `app/jarl_client.py`：**先做技术验证**——用 httpx 直接 POST JARL 查询表单，能解析出会员信息就用这条路；不行切 Playwright，更新 Charter §5
- [ ] `app/main.py`：FastAPI，单页面，文本框 + 提交按钮
- [ ] 手动测试：粘贴 `JA1RL` → 看到结果

**风险点**：JARL 站点可能有 ViewState/反爬。验证步骤里**先用浏览器打开页面看一次表单结构**，记下隐藏字段，再写抓取代码。

---

## v0.2 — 日本呼号筛选 + 缓存

**目标**：批量呼号能正确分流。
**完成定义**：粘贴 10 个混合呼号（含 `JA1RL`, `BG7XXX`, `W1AW`, `JA1RL/P`），日本呼号被识别并查询，非日本被标记跳过；重复查询命中缓存。

- [ ] `app/callsign_filter.py`：前缀匹配 + 后缀剥离
  - 单测：`JA1RL/P` → `JA1RL`，`W1AW` → 跳过，`7K1ABC/MM` → `7K1ABC`
- [ ] `app/cache.py`：SQLite 表 + 读写函数
  - 表：`callsign TEXT PRIMARY KEY, is_member INT, name TEXT, qth TEXT, queried_at TIMESTAMP, raw TEXT`
- [ ] Web UI 增加进度区：`已查 X/Y, 会员 N, 缓存命中 M`
- [ ] 限速：`asyncio.sleep(1.0)` 之间每两次请求

---

## v0.3 — ADI 文件上传

**目标**：拖入 ADI 文件能跑出结果。
**完成定义**：上传一个真实 ADI 文件，自动去重提取呼号，跑完出 CSV。

- [ ] `app/adi_parser.py`：解析 ADIF（`<CALL:N>VALUE`），返回呼号集合
  - 单测：标准 ADIF、ADI（无头部）、带特殊字符的样本
- [ ] Web UI 增加上传组件
- [ ] CSV 导出端点：`GET /export.csv`

---

## v0.4 — QRZ Logbook API 拉取

**目标**：输入 API key + 时间范围，自动拉取并查询。
**完成定义**：用测试 key 拉取真实日志，端到端跑完。

- [ ] `app/qrz_client.py`：调用 QRZ Logbook API（`https://logbook.qrz.com/api`），按 DATE 范围筛选
  - 注意：QRZ API 是 POST + URL-encoded，返回 ADI 格式
- [ ] Web UI 增加 key 输入框 + 起止日期选择
- [ ] **测试时 key 从 `.env` 读，UI 输入框留空也支持**——避免重复粘贴
- [ ] 端到端验证：用真实 key（在 `.env`）拉一段，记录结果

---

## v0.5 — 结果展示打磨 + 验证文档

**目标**：结果表能用，验证流程留痕。
**完成定义**：表格可筛选/排序；`docs/verification/` 有完整截图和说明。

- [ ] 结果表加筛选：仅会员 / 全部
- [ ] 结果表加排序：按 QTH、按查询时间
- [ ] `scripts/check_secrets.sh`：grep 检测疑似 API key、QRZ key 前缀
- [ ] `scripts/verify.py`：自动跑 §3.2 三条验证标准（正例 / 反例 / 端到端）
- [ ] `docs/verification/`：截图 + 文字说明
- [ ] README：完整安装运行说明

---

## v1.0 — 发布

**目标**：仓库公开，readme 完整，他人能开箱即用。

- [ ] README 完善：安装、配置、运行、限速说明、免责声明
- [ ] LICENSE：MIT
- [ ] `scripts/check_secrets.sh` 通过
- [ ] 创建 GitHub repo `jarl-member-search`（public）
- [ ] 首次推送

---

---

## v1.1 — 流式结果 + ADI 成员过滤导出

**目标**：长查询不再让人干等；ADI 输入时能一键导出"只剩会员"的 ADI。
**完成定义**：
- 用 QRZ 拉一大段（>50 条日本呼号），结果在第一批查完后就开始出现在表格里
- 上传含若干会员/非会员的 ADI，点"Export members-only ADI"，下载的 .adi 在 Cloudlog/Log4OM 里能正常导入，会员 QSO 数 = 表里 yes 数

- [ ] `JarlClient.query_iter(callsigns)`：async generator，逐批 yield `list[JarlResult]`
- [ ] `app/adi_parser.py` 加 `extract_records(data)` → `(header, [(record_text, callsign)])`，字节保留
- [ ] `app/adi_parser.py` 加 `filter_records(data, keep_callsign_set)` → bytes
- [ ] FastAPI `POST /search.stream` → `StreamingResponse(application/x-ndjson)`，事件：
      `{event:'start', queryable, skipped}` → `{event:'result', ...}` × N → `{event:'done'}`
- [ ] FastAPI `POST /export.adi` → 重跑 search，提取 yes 集合，调用 `filter_records`，返回过滤 ADI
- [ ] 前端：用 fetch + `body.getReader()` 流式读 NDJSON，append 行；提交后保留 file input，
      搜索完成后显示"Export members-only ADI"按钮（仅当上传了 ADI 时）
- [ ] 旧 `/search` HTML POST 端点保留（无 JS 回退）
- [ ] 单测：filter_records 字节保留、CALL 大小写、portable 后缀
- [ ] verify.py 第 4 步：filter 一个含 JA1RL+W1AW 的 ADI，校验只剩 JA1RL 那条

---

## 备选 / 后续考虑（v1.x+）

仅记录，不承诺。任何启动前先和用户对齐，更新 Charter §3 / §4。

- ADI 写回（给 QSO 加 `APP_JARL_MEMBER` 字段）
- LoTW / eQSL 集成（看哪些会员同时在用）
- 历史查询统计（"我和多少 JARL 会员通联过"）
- 命令行子命令（不强求 Web，给老派用户）
- 配置化的限速 / 缓存有效期

---

## 进度跟踪

每个迭代完成后：
1. 跑一遍 Charter §3.2 验证标准
2. 在本文件对应迭代下勾选完成项
3. 如果有发现需要写进 Charter 的事实（例如 JARL 改了表单结构），同步更新 Charter
