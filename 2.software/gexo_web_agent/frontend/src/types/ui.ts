export const STAGES = ["sense", "reason", "act"] as const;

export type StageId = (typeof STAGES)[number];

export const STAGE_LABELS: Record<StageId, string> = {
  sense: "SENSE",
  reason: "REASON",
  act: "ACT",
};

export const JOINTS = [
  { id: "lh", short: "LH", name: "Left hip" },
  { id: "lk", short: "LK", name: "Left knee" },
  { id: "rh", short: "RH", name: "Right hip" },
  { id: "rk", short: "RK", name: "Right knee" },
] as const;
