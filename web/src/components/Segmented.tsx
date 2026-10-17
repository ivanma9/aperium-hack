"use client";

import { useRef, type KeyboardEvent } from "react";

export interface SegmentedItem<T extends string> {
  id: T;
  label: string;
}

/** Glass pill tablist with roving focus (←/→/Home/End). */
export function Segmented<T extends string>({
  items,
  value,
  onChange,
  label,
  size = "sm",
  className = "",
  idPrefix,
  controls,
}: {
  items: readonly SegmentedItem<T>[];
  value: T;
  onChange: (id: T) => void;
  label: string;
  size?: "sm" | "lg";
  className?: string;
  /** When set, tabs get ids `${idPrefix}-${id}` so a tabpanel can reference them. */
  idPrefix?: string;
  /** id of the tabpanel these tabs control. */
  controls?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = items.findIndex((it) => it.id === value);
    const next =
      e.key === "ArrowRight" ? (i + 1) % items.length
      : e.key === "ArrowLeft" ? (i - 1 + items.length) % items.length
      : e.key === "Home" ? 0
      : e.key === "End" ? items.length - 1
      : -1;
    if (next < 0) return;
    e.preventDefault();
    onChange(items[next].id);
    refs.current[next]?.focus();
  };

  return (
    <div
      role="tablist"
      aria-label={label}
      className={`glass segmented ${size === "lg" ? "lg" : ""} ${className}`}
      onKeyDown={onKeyDown}
    >
      {items.map((it, i) => {
        const selected = it.id === value;
        return (
          <button
            key={it.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={idPrefix ? `${idPrefix}-${it.id}` : undefined}
            aria-controls={controls}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(it.id)}
          >
            {it.label}
          </button>
        );
      })}
    </div>
  );
}
