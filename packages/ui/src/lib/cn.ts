/** Tiny class-name joiner. Accepts strings, falsy values, arrays and
 *  `{ "class-name": condition }` maps. No dependencies. */
export type ClassValue =
  | string
  | number
  | null
  | undefined
  | false
  | ClassValue[]
  | { [className: string]: unknown };

export function cn(...inputs: ClassValue[]): string {
  const out: string[] = [];
  const walk = (value: ClassValue): void => {
    if (!value && value !== 0) return;
    if (typeof value === "string" || typeof value === "number") {
      out.push(String(value));
    } else if (Array.isArray(value)) {
      value.forEach(walk);
    } else if (typeof value === "object") {
      for (const key of Object.keys(value)) if (value[key]) out.push(key);
    }
  };
  inputs.forEach(walk);
  return out.join(" ");
}
