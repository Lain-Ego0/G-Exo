import { createContext, useContext } from "react";

export type Lang = "zh" | "en";

export const LangContext = createContext<{ lang: Lang; toggle: () => void }>({
  lang: "zh",
  toggle: () => {},
});

export function useLang() {
  return useContext(LangContext);
}

const dict = {
  nav: {
    features: { zh: "能力", en: "Features" },
    loop: { zh: "闭环", en: "Closed Loop" },
    specs: { zh: "参数", en: "Specs" },
    cockpit: { zh: "驾驶舱", en: "Cockpit" },
    launch: { zh: "进入驾驶舱", en: "Launch Cockpit" },
  },
  hero: {
    kicker: { zh: "物理智能 · PHYSICAL AI", en: "PHYSICAL AI · 物理智能" },
    titleA: { zh: "让每一步", en: "Every step," },
    titleB: { zh: "都被理解", en: "understood." },
    desc: {
      zh: "G-EXO 四自由度主动下肢外骨骼：感知穿戴者意图，经安全校验推理，输出恰到好处的助力。",
      en: "G-EXO is a four-DOF active lower-limb exoskeleton: it senses wearer intent, reasons through a safety-guarded pipeline, and delivers precisely metered assistance.",
    },
    ctaPrimary: { zh: "进入驾驶舱", en: "Launch Cockpit" },
    ctaSecondary: { zh: "了解闭环", en: "Explore the Loop" },
    scroll: { zh: "向下滚动", en: "Scroll" },
  },
  stats: {
    items: [
      { value: 4, suffix: "", zh: "自由度主动关节", en: "Active DOF Joints" },
      { value: 3, suffix: "", zh: "阶段智能闭环", en: "Stage Closed Loop" },
      { value: 100, suffix: "ms", zh: "指令确认延迟", en: "Command Ack Latency", prefix: "<" },
      { value: 8, suffix: "", zh: "板载传感通道", en: "Onboard Sensor Channels" },
    ],
  },
  loop: {
    kicker: { zh: "SENSE → REASON → ACT", en: "SENSE → REASON → ACT" },
    title: { zh: "一个闭环，而非三个功能", en: "One loop, not three features" },
    desc: {
      zh: "信息架构即控制架构。每一次助力决策都可被追溯回传感数据与安全闸门。",
      en: "The information architecture is the control architecture. Every assist decision traces back to sensor data and safety gates.",
    },
    cards: [
      {
        key: "sense",
        zh: { title: "感知 SENSE", desc: "四路 IMU 与关节编码器实时描绘穿戴者步态，CAN 总线回传电机健康。", tag: "IMU ×4 · ENCODER ×4 · CAN" },
        en: { title: "SENSE 感知", desc: "Four IMUs and joint encoders capture gait in real time; CAN bus reports motor health.", tag: "IMU ×4 · ENCODER ×4 · CAN" },
      },
      {
        key: "reason",
        zh: { title: "推理 REASON", desc: "LLM 意图解析经过五道安全校验闸门，任何指令先证明安全，再谈智能。", tag: "INTENT → SAFETY GATE ×5 → ROS 2" },
        en: { title: "REASON 推理", desc: "LLM intent parsing passes five safety-guard stages — commands prove safety before intelligence.", tag: "INTENT → SAFETY GATE ×5 → ROS 2" },
      },
      {
        key: "act",
        zh: { title: "执行 ACT", desc: "助力 / 阻尼双模式，全局助力比例 ±10% 精细步进，命令以控制器回执为准。", tag: "ASSIST · DAMPING · ±10% STEP" },
        en: { title: "ACT 执行", desc: "Assist and damping modes with ±10% assist-ratio steps; commands count only when acknowledged.", tag: "ASSIST · DAMPING · ±10% STEP" },
      },
    ],
  },
  features: {
    kicker: { zh: "CAPABILITIES", en: "CAPABILITIES" },
    title: { zh: "为真实穿戴而生", en: "Built for real wearers" },
    cards: [
      {
        zh: { title: "意图级交互", desc: "用自然语言告诉它“上坡帮我省点力”，Agent 将意图编译为受安全约束的控制指令。" },
        en: { title: "Intent-level Interaction", desc: "Say “help me climb this hill” — the agent compiles intent into safety-bounded control commands." },
      },
      {
        zh: { title: "安全先于智能", desc: "急停、故障、写保护三重硬约束常驻界面顶部，任何 AI 决策无法越过安全轨。" },
        en: { title: "Safety before Intelligence", desc: "E-stop, fault and write-protection rails stay visible; no AI decision crosses the safety rail." },
      },
      {
        zh: { title: "诚实的数据", desc: "缺数据就显示 --，绝不编造合理数值。估算扭矩以 EST 明确标注。" },
        en: { title: "Honest Telemetry", desc: "Missing data shows --, never fabricated values. Estimated torque is explicitly labelled EST." },
      },
      {
        zh: { title: "Web 即座舱", desc: "浏览器直连机器人，无需安装。桌面大屏与手机小屏同一套响应式控制台。" },
        en: { title: "Browser as Cockpit", desc: "Connect to the robot from any browser — one responsive console for desktop and phone." },
      },
    ],
  },
  specs: {
    kicker: { zh: "SPECIFICATIONS", en: "SPECIFICATIONS" },
    title: { zh: "技术参数", en: "Technical Specifications" },
    rows: [
      { zh: ["关节配置", "主动髋 ×2 + 主动膝 ×2"], en: ["Joint Layout", "Active hip ×2 + active knee ×2"] },
      { zh: ["传感", "IMU ×4 · 关节编码器 ×4 · 母线电压/电流"], en: ["Sensing", "IMU ×4 · joint encoder ×4 · bus V/I"] },
      { zh: ["通信", "CAN 总线 · WebSocket 遥测"], en: ["Comms", "CAN bus · WebSocket telemetry"] },
      { zh: ["控制栈", "Web 座舱 · Agent 安全校验 · ROS 2 控制器"], en: ["Control Stack", "Web cockpit · safety-guarded agent · ROS 2 controller"] },
      { zh: ["模式", "助力 ASSIST / 阻尼 DAMPING，助力比例 0.3–1.0"], en: ["Modes", "ASSIST / DAMPING, assist ratio 0.3–1.0"] },
    ],
    caption: { zh: "四关节人体映射 / FOUR-JOINT BODY MAP", en: "FOUR-JOINT BODY MAP / 四关节人体映射" },
  },
  cta: {
    kicker: { zh: "LIVE DEMO", en: "LIVE DEMO" },
    title: { zh: "亲眼看看闭环运转", en: "Watch the loop run live" },
    desc: {
      zh: "打开驾驶舱，实时遥测、安全校验流程与助力控制一屏尽览。",
      en: "Open the cockpit: live telemetry, the safety-guard flow and assist control on one screen.",
    },
    button: { zh: "启动驾驶舱", en: "Launch Cockpit" },
    note: { zh: "本地演示：mock 场景可切换急停 / 故障 / 过热等 8 种状态", en: "Local demo: 8 mock scenarios including e-stop, fault and overheat" },
  },
  footer: {
    line: { zh: "G-EXO · 物理 AI 黑客松 2026", en: "G-EXO · Physical AI Hackathon 2026" },
    sub: { zh: "SENSE → REASON → ACT", en: "SENSE → REASON → ACT" },
  },
} as const;

export function t(entry: { zh: string; en: string }, lang: Lang): string {
  return entry[lang];
}

export default dict;
