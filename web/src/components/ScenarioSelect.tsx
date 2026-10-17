"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { SCENARIOS, type ScenarioConfig } from "@/config/scenarios";

function hint(s: ScenarioConfig) {
  const sign = s.depth > 0 ? "−" : s.depth < 0 ? "+" : "±";
  return `flow ${sign}${Math.round(Math.abs(s.depth) * 100)}%`;
}

/**
 * Scenario picker: a button + listbox that opens upward. Keyboard: ↑/↓/Home/End
 * move, Enter/Space choose, Esc closes and returns focus; closes on outside click.
 */
export function ScenarioSelect({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();
  const current = SCENARIOS.find((s) => s.id === value) ?? SCENARIOS[0];

  const openList = () => {
    setActive(Math.max(0, SCENARIOS.findIndex((s) => s.id === value)));
    setOpen(true);
  };
  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  };
  const choose = (i: number) => {
    onChange(SCENARIOS[i].id);
    close(true);
  };

  useEffect(() => {
    if (!open) return;
    listRef.current?.focus();
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const onTriggerKeyDown = (e: KeyboardEvent) => {
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      openList();
    }
  };

  const onListKeyDown = (e: KeyboardEvent) => {
    const last = SCENARIOS.length - 1;
    switch (e.key) {
      case "ArrowDown":
        setActive((a) => Math.min(last, a + 1));
        break;
      case "ArrowUp":
        setActive((a) => Math.max(0, a - 1));
        break;
      case "Home":
        setActive(0);
        break;
      case "End":
        setActive(last);
        break;
      case "Enter":
      case " ":
        choose(active);
        break;
      case "Escape":
        close(true);
        break;
      case "Tab":
        setOpen(false);
        return;
      default:
        return;
    }
    e.preventDefault();
  };

  return (
    <div ref={rootRef} style={{ display: "contents" }}>
      <button
        ref={triggerRef}
        type="button"
        className="scenario-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`Scenario: ${current.name}`}
        onClick={() => (open ? close(false) : openList())}
        onKeyDown={onTriggerKeyDown}
      >
        <span className="label">Scenario</span>
        <span className="dot" style={{ background: "var(--accent)" }} />
        {current.name}
        <svg className="chevron" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M2.5 4.5 L6 8 L9.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label="Geopolitical scenario"
          aria-activedescendant={`${listId}-${SCENARIOS[active].id}`}
          tabIndex={-1}
          className="glass scenario-list"
          onKeyDown={onListKeyDown}
        >
          {SCENARIOS.map((s, i) => {
            const selected = s.id === current.id;
            return (
              <li
                key={s.id}
                id={`${listId}-${s.id}`}
                role="option"
                aria-selected={selected}
                data-active={i === active}
                className="scenario-option"
                onPointerEnter={() => setActive(i)}
                onClick={() => choose(i)}
              >
                <span style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  <span className="dot" style={{ background: selected ? "var(--accent)" : "rgba(232,238,243,0.35)" }} />
                  {s.name}
                </span>
                <span className="hint">{hint(s)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
