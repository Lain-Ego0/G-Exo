import { useEffect, useRef } from "react";
import { Check, ShieldCheck, X } from "lucide-react";

import { modeWriteBlocker } from "../../lib/safety";
import type { RobotCommandView } from "../../hooks/useRobotCommand";
import type { RobotSocketView, RobotMode } from "../../types/robot";

export function ModeConfirmDialog({
  commands,
  robot,
}: {
  commands: RobotCommandView;
  robot: RobotSocketView;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const command = commands.lastCommand;
  const open = command?.status === "pending_confirmation" && command.action === "set_mode";
  const rawMode = command?.params.mode;
  const targetMode: RobotMode | null = rawMode === "assist" || rawMode === "damping"
    ? rawMode
    : null;
  const blocker = targetMode ? modeWriteBlocker(robot, targetMode) : "MODE DATA UNAVAILABLE";
  const { busy, confirmPending } = commands;

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    cancelRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        event.preventDefault();
        void confirmPending(false);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [cancelRef.current, confirmRef.current].filter(
        (item): item is HTMLButtonElement => Boolean(item && !item.disabled),
      );
      if (focusable.length === 0) return;
      const currentIndex = focusable.indexOf(document.activeElement as HTMLButtonElement);
      const nextIndex = event.shiftKey
        ? (currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1)
        : (currentIndex + 1) % focusable.length;
      event.preventDefault();
      focusable[nextIndex].focus();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [busy, confirmPending, open]);

  if (!open || !targetMode) return null;
  const label = targetMode === "assist" ? "Assist" : "Damping";

  return (
    <div className="dialog-backdrop">
      <section
        aria-describedby="mode-dialog-description"
        aria-labelledby="mode-dialog-title"
        aria-modal="true"
        className="mode-dialog"
        ref={dialogRef}
        role="dialog"
      >
        <header>
          <span className="dialog-icon"><ShieldCheck aria-hidden="true" size={20} /></span>
          <div>
            <span className="section-index">SAFETY CONFIRMATION</span>
            <h2 id="mode-dialog-title">Switch to {label} mode?</h2>
          </div>
        </header>
        <p id="mode-dialog-description">
          Mode changes are permitted only while the wearer is stationary and the controller safety state is clear.
        </p>
        <dl>
          <div><dt>TARGET</dt><dd>{label.toUpperCase()}</dd></div>
          <div><dt>REQUEST ID</dt><dd>{command.request_id}</dd></div>
          <div><dt>SAFETY STATE</dt><dd>{blocker ?? "READY FOR CONFIRMATION"}</dd></div>
        </dl>
        <footer>
          <button
            className="dialog-button secondary"
            disabled={commands.busy}
            onClick={() => void commands.confirmPending(false)}
            ref={cancelRef}
            type="button"
          >
            <X aria-hidden="true" size={17} />Cancel
          </button>
          <button
            className="dialog-button primary"
            disabled={commands.busy || blocker !== null}
            onClick={() => void commands.confirmPending(true)}
            ref={confirmRef}
            type="button"
          >
            <Check aria-hidden="true" size={17} />Confirm switch
          </button>
        </footer>
      </section>
    </div>
  );
}
