import type { QuaternionData, Vector3Data } from "../types/robot";

export interface EulerAngles extends Vector3Data {}

export function quaternionToEuler(quaternion: QuaternionData | null): EulerAngles | null {
  if (!quaternion) return null;
  const norm = Math.hypot(quaternion.x, quaternion.y, quaternion.z, quaternion.w);
  if (!Number.isFinite(norm) || norm < 1e-9) return null;
  const x = quaternion.x / norm;
  const y = quaternion.y / norm;
  const z = quaternion.z / norm;
  const w = quaternion.w / norm;

  const roll = Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y));
  const pitchTerm = 2 * (w * y - z * x);
  const pitch = Math.asin(Math.max(-1, Math.min(1, pitchTerm)));
  const yaw = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
  return { x: roll, y: pitch, z: yaw };
}

export function radiansToDegrees(value: number): number {
  return value * 180 / Math.PI;
}
