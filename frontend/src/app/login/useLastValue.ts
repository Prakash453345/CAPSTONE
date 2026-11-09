import { useRef } from "react";

/** The last non-empty value, so a message can finish fading out after it is cleared. */
export function useLastValue(value: string | null): string {
  const last = useRef("");
  if (value) last.current = value;
  return value ?? last.current;
}
