import { Gauge, Minus, Plus, Radio, Zap } from "lucide-react";

import type { RobotCommandView } from "../../hooks/useRobotCommand";
import { assistWriteBlocker, modeWriteBlocker } from "../../lib/safety";
import type { RobotSocketView } from "../../types/robot";

export function SimulatedModeControl({
  commands,
  robot,
}: {
  commands: RobotCommandView;
  robot: RobotSocketView;
}) {
  const state = robot.snapshot?.state;
  const assistPercent = typeof state?.assist_ratio === "number"
    ? Math.round(state.assist_ratio * 100) : null;
  const assistBlocker = modeWriteBlocker(robot, "assist");
  const dampingBlocker = modeWriteBlocker(robot, "damping");
  const decreaseBlocker = assistWriteBlocker(robot, -0.1);
  const increaseBlocker = assistWriteBlocker(robot, 0.1);

  return (
    <section className="sim-control" aria-labelledby="sim-control-title">
      <header>
        <div>
          <span className="sim-control-kicker">SIMULATED CONTROL / 模拟控制</span>
          <h2 id="sim-control-title">外骨骼助力模式</h2>
        </div>
        <span className="sim-control-status" data-state={robot.connection}>
          <Radio aria-hidden="true" size={14} />
          {robot.connection === "online" ? "模拟器在线" : "模拟器未连接"}
        </span>
      </header>

      <div className="sim-control-body">
        <div className="sim-mode-group">
          <span>运行模式</span>
          <div className="sim-mode-segment">
            <button
              aria-pressed={state?.mode === "assist"}
              disabled={commands.busy || assistBlocker !== null}
              onClick={() => void commands.executeAction("set_mode", { mode: "assist" })}
              title={assistBlocker ?? "切换至助力模式"}
              type="button"
            ><Zap aria-hidden="true" size={19} />助力模式 <small>ASSIST</small></button>
            <button
              aria-pressed={state?.mode === "damping"}
              disabled={commands.busy || dampingBlocker !== null}
              onClick={() => void commands.executeAction("set_mode", { mode: "damping" })}
              title={dampingBlocker ?? "切换至阻尼模式"}
              type="button"
            ><Gauge aria-hidden="true" size={19} />阻尼模式 <small>DAMPING</small></button>
          </div>
        </div>

        <div className="sim-assist-group">
          <span>全局助力比例</span>
          <div className="sim-assist-stepper">
            <button aria-label="降低助力比例" disabled={commands.busy || decreaseBlocker !== null}
              onClick={() => void commands.executeAction("adjust_assist", { delta: -0.1 })}
              title={decreaseBlocker ?? "降低 10%"} type="button"><Minus size={20} /></button>
            <strong>{assistPercent ?? "--"}<small>%</small></strong>
            <button aria-label="提高助力比例" disabled={commands.busy || increaseBlocker !== null}
              onClick={() => void commands.executeAction("adjust_assist", { delta: 0.1 })}
              title={increaseBlocker ?? "提高 10%"} type="button"><Plus size={20} /></button>
          </div>
        </div>

        <div className="sim-command-state" role="status">
          <span>命令状态</span>
          <strong>{commands.busy ? "执行中" : commands.lastCommand?.status === "pending_confirmation" ? "等待确认" : commands.lastCommand?.status === "success" ? "已执行" : "就绪"}</strong>
          {commands.lastCommand?.status === "pending_confirmation" ? (
            <div className="sim-confirm-actions">
              <button type="button" onClick={() => void commands.confirmPending(true)}>确认切换</button>
              <button type="button" onClick={() => void commands.confirmPending(false)}>取消</button>
            </div>
          ) : (
            <small>{commands.lastCommand?.message ?? "模式与比例来自保留的 mock 控制器"}</small>
          )}
        </div>
      </div>
      <p className="sim-control-note">此区域为模拟控制，不代表开发板当前电机、扭矩或执行器状态。下方 IMU 数据来自 ROS 实时话题。</p>
    </section>
  );
}
