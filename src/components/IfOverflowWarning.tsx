import { useRuntimeStore } from "../stores";

export function IfOverflowWarning() {
  const active = useRuntimeStore((state) => state.ifOverflow);
  if (!active) return null;
  return (
    <div
      className="if-overflow-warning"
      role="alert"
      title="IF path saturated. Increase reference level or attenuation."
    >
      IF OVERFLOW
    </div>
  );
}
