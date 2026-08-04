# G-EXO 驾驶舱主视觉优化建议与实施方案

- 分支：`feature/k3-main-visual`（基于 `integration/k3-web-agent` @ `3d23afb`）
- 范围：`2.software/gexo_web_agent/frontend`（双语驾驶舱 Web UI）
- 约束：遵守 `frontend_design.md` 已定稿的设计系统（SENSE→REASON→ACT 闭环语言、Hardware truth 原则），本方案只做**视觉层增强**，不改信息架构与交互逻辑。

---

## 1. 现状评估

### 1.1 已有优势（应保留）
- 设计语言统一、克制：深蓝底 `#071426` + 三阶段语义色（青/紫/琥珀）+ 1px 细边框玻璃面板，全部 token 化（`tokens.css`）。
- 可访问性讲究：aria、focus-visible、`prefers-reduced-motion` 均已覆盖。
- "闭环脊柱"（ClosedLoopSpine）作为签名视觉装置的定位明确（frontend_design.md §2.6）。

### 1.2 主视觉短板（按影响排序）
| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 1 | **无品牌主视觉**：无 logo、无 favicon、无 OG 元信息，品牌仅靠纯文字 "G-EXO" wordmark | `index.html`、`public/` | 演示/截图传播时无识别度 |
| 2 | **首屏视觉"平"**：纯色深底，无层次光源、无景深；唯一视觉重心是三列等宽面板，第一眼无焦点 | `cockpit.css` 全局 | 黑客松演示"第一眼冲击力"不足 |
| 3 | **外骨骼主图质量受限**：`gexo-exoskeleton.png` 非抠图（带涂抹纹理背景，1.4MB），靠滤镜硬融合；关节节点百分比绝对定位，换图即错位 | `SensePanel`、`cockpit.css:634-719` | SENSE 面板是首屏左列，是主视觉核心载体 |
| 4 | **中文字体未落地**：`Noto Sans SC` 仅声明未自托管，回退不可控 | `fonts.css`、`tokens.css:26-27` | 双语标题的字体气质不统一 |
| 5 | **动效过于克制**：全项目仅 1 个一次性 keyframes，无呼吸/扫描/数据流动感，"活体座舱"感弱 | `cockpit.css:411-418` | 与"物理 AI 座舱"的产品叙事不匹配 |
| 6 | **颜色 token 泄漏**：TSX 图表层硬编码 hex（TelemetryDock `JOINT_COLORS` 等约 23 处），主题不可演进 | `TelemetryDock.tsx`、`ActPanel.tsx:44-48` | 后续主视觉换色成本高 |
| 7 | **Reason 面板永久"离线"徽章硬编码**，与真实 Agent 状态矛盾 | `ReasonPanel.tsx:184-187` | 演示时视觉上是"坏掉的"中枢 |

---

## 2. 主视觉方向建议（三选一，推荐 A）

### 方案 A：「活体蓝图 Living Blueprint」（推荐）
保持现有工程控制台基调，把**闭环脊柱 + 外骨骼关节映射**升级为唯一的动态视觉英雄：
- 外骨骼图抠图/矢量化后置于 SENSE 面板视觉中心，四关节节点带微光脉冲（跟随真实遥测节拍）。
- 闭环脊柱流动化：感知→推理→执行的数据流用低亮度渐变流光（`prefers-reduced-motion` 下退化为静态）。
- 首屏背景增加极克制的深蓝径向光源（面板后方 5-8% 亮度的光晕），制造景深但不破坏"工程诚实"气质。
- **优点**：不推翻已定稿设计系统，改动收敛在 CSS + 一个 SVG 资产；风险最低，评委一眼记住"闭环"。

### 方案 B：「海报延展 Poster-Extended」
按 `frontend_design.md §3` 的海报视觉做一张演示封面（启动屏/加载屏）：大字标 G-EXO + 外骨骼剪影 + 三阶段色带，进入座舱后收起。
- **优点**：黑客松路演开场有仪式感；**缺点**：增加一个视图状态，与"hardware truth"原则有张力。

### 方案 C：「数据霓虹」
全面加强霓虹发光、网格透视地板、扫描线等赛博元素。
- **不推荐**：与已定稿的克制工程风冲突，改动面大，且降低数据可读性。

---

## 3. 具体优化项（优先级排序）

### P0 — 基础修复（视觉正确性，约 0.5 天）
1. **中文字体自托管**：引入 `@fontsource/noto-sans-sc`（仅 400/600 常用字重子集），fonts.css 统一加载策略。
2. **favicon + OG 元信息**：基于 G-EXO wordmark 生成 SVG favicon（深底 + 青色 G 形闭环箭头），`index.html` 补 title/description/og:image。
3. **Reason 面板离线徽章状态化**：`data-state` 绑定真实 `apiReachable`，消除硬编码 "分析引擎离线"（`ReasonPanel.tsx:184-187`）。
4. **颜色 token 收口**：`TelemetryDock.tsx` 的 `JOINT_COLORS` 等改读 CSS 变量（`getComputedStyle` 一次性读取或 CSS 变量经 `var()` 注入 SVG `stroke`）；`ActPanel.tsx:44-48` 内联色改 CSS 类。

### P1 — 主视觉英雄区（方案 A 主体，约 1-2 天）
5. **外骨骼资产升级**：
   - 短期：现有 PNG 抠图去底（保留深蓝调色），WebP 化压缩至 <300KB，补 `srcset`；
   - 中期：重绘为线性蓝图风 SVG（描边 1.5px、关节点可独立寻址），关节节点用 SVG 内 `<g id="joint-lh">` 定位，彻底摆脱百分比绝对定位换图错位问题（`cockpit.css:701-719`、`:2216-2224`）。
6. **闭环脊柱动效**：新增 1 个循环 keyframes `spine-flow`（6-8s 慢速、低亮度渐变位移动画），仅在对应 stage 活跃时播放；reduced-motion 下静态。
7. **首屏景深光**：`cockpit-main` 背景加 2 个 `radial-gradient` 光晕（sense 青在左、act 琥珀在右，亮度 ≤8%），纯 CSS 实现，零依赖。
8. **wordmark 精修**：G-EXO 字标加 1px 青色下划线收尾为闭环箭头 ↻ 符号（呼应闭环叙事），Barlow Condensed 字距微调。

### P2 — 氛围与传播（约 1 天）
9. **演示模式（Demo Mode）**：URL 参数 `?demo=1` 时放大 hero 区、隐藏 DebugDrawer，供路演投屏。
10. **加载/空态品牌化**：`DATA UNAVAILABLE` 大面积灰态增加品牌纹理底（极淡蓝图网格），离线不再"空"。
11. **截图/分享物料**：输出 1920×1080 OG 图一张（驾驶舱截图 + 字标合成），用于 README 与黑客松提交页。

---

## 4. 实施计划

| 阶段 | 内容 | 产出 | 验收 |
|------|------|------|------|
| Step 1 (P0) | 字体/favicon/token 收口/离线徽章 | 4 个小提交 | `vite build` 通过；离线徽章随 mock 切换变化；图表色与 tokens.css 一致 |
| Step 2 (P1) | 外骨骼资产 + 脊柱动效 + 景深受 | hero 区视觉升级 | 首屏截图对比；reduced-motion 降级正常；Lighthouse 性能不降 |
| Step 3 (P2) | Demo 模式 + 空态 + OG 图 | 传播物料 | `?demo=1` 投屏效果评审 |

**改动文件边界**（不动逻辑层）：
- 仅允许改：`frontend/src/styles/*.css`、`frontend/index.html`、`frontend/public/`、`frontend/src/components/**` 中的 className/内联样式。
- 禁止改：`hooks/`、`lib/`、`types/` 的行为逻辑（Reason 离线徽章仅改取值来源）。

**分支策略**：本分支 `feature/k3-main-visual` 承载全部主视觉改动，按 Step 1→3 提交；评审通过后合回 `integration/k3-web-agent`。

---

## 6. 实施状态（2026-08-04 更新）

**已完成（本分支，构建 `tsc -b && vite build` 通过，截图验证通过）：**

- P0-1 中文字体自托管：`@fontsource/noto-sans-sc`（latin + chinese-simplified，400/600），`fonts.css` 统一加载。注意：中文字重文件较大（woff2 约 1.1MB/字重），本地演示场景可接受，线上部署建议开启 brotli 或改用可变字体子集。
- P0-2 `public/favicon.svg`（深底 + 青色闭环箭头 + 琥珀节点），`index.html` 补 description / OG 元信息 / 双语 title。
- P0-3 Reason 面板状态化：头部徽章 / R.01 身份卡 / R.02 EVENT API 全部绑定 `robot.apiReachable`（在线绿、离线琥珀），消除硬编码“离线”。
- P0-4 图表层 token 收口：`TelemetryDock.tsx` 所有 hex 改为运行时读取 `tokens.css` 变量（`--joint-*` / `--gexo-act` / `--gexo-reason` / `--gexo-success`，含 SSR 回退）。ActPanel 经查已用 `var()` 内联，无需改。
- P1-1 闭环脊柱流动：`data-flow` 仅在连接 online 时启用 7s 渐变流光 + 活跃节点呼吸（与既有事件脉冲不冲突）；reduced-motion 自动降级。
- P1-2 首屏景深受：`.cockpit-main::before` 双层 radial-gradient（青 7% / 琥珀 5%），`z-index:-1` 衬于面板之后。
- P1-3 wordmark 精修：G-EXO 字标追加青色闭环箭头 SVG（`.wordmark-loop`），字距 0.02em。
- P1-4 外骨骼主图融合：蓝图网格底（28px 细格）+ 椭圆边缘羽化 mask（替代抠图方案，零资产成本消除硬边矩形）；在线关节节点呼吸脉冲。

**未做（留待后续迭代）：** P1-5 外骨骼重绘 SVG（中期）、P2 全部（demo 模式 / 空态纹理 / OG 合成图）。

---

## 5. 风险与注意
- 新增循环动效必须全程 `prefers-reduced-motion` 可降级（沿用 `global.css:106` 现有模式）。
- 光晕/发光效果亮度上限 8-10%，避免破坏数据密集面板的可读性对比度（WCAG AA：正文对比度 ≥4.5）。
- 外骨骼 PNG 若重绘 SVG，需同步更新 SensePanel 关节节点定位逻辑与移动端断点坐标（`cockpit.css:2216-2224`）。
