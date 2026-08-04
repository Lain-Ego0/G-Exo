/**
 * Aurora (React Bits style): slow drifting gradient light field.
 * Pure CSS animation, sits absolutely behind content.
 */
export function Aurora({ className }: { className?: string }) {
  return (
    <div aria-hidden="true" className={`aurora ${className ?? ""}`}>
      <span className="aurora-blob aurora-blob-a" />
      <span className="aurora-blob aurora-blob-b" />
      <span className="aurora-blob aurora-blob-c" />
    </div>
  );
}
