"use client";

import { useState, type KeyboardEvent } from "react";
import { cn } from "../ui";

function normalise(raw: string, mode: "hashtag" | "keyword"): string[] {
  // hashtags: split on spaces/commas and add "#"; keywords: split on commas only, so "machine learning" stays one
  const parts = mode === "hashtag" ? raw.split(/[\s,]+/) : raw.split(/[,\n]+/);
  return parts
    .map((t) => t.trim().replace(/^#+/, "").replace(/\s+/g, " ").toLowerCase())
    .filter(Boolean)
    .map((t) => (mode === "hashtag" ? `#${t}` : t));
}

export function TagInput({
  value,
  onChange,
  disabled,
  suggestions = [],
  placeholder = "#pythonhiring, #pythondeveloper",
  mode = "hashtag",
  ariaLabel,
}: {
  value: string[];
  onChange: (tags: string[]) => void;
  disabled?: boolean;
  suggestions?: string[];
  placeholder?: string;
  mode?: "hashtag" | "keyword";
  ariaLabel?: string;
}) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const next = [...value];
    for (const t of normalise(raw, mode)) if (!next.includes(t)) next.push(t);
    onChange(next);
    setDraft("");
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === "," || (e.key === " " && mode === "hashtag")) {
      e.preventDefault();
      if (draft.trim()) add(draft);
    } else if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  };

  const unused = suggestions.filter((s) => !value.includes(s));

  return (
    <div>
      <div
        className={cn(
          "flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1.5 transition-colors hover:border-zinc-300",
          "focus-within:border-brand-500 focus-within:ring-3 focus-within:ring-brand-100",
          disabled && "bg-zinc-50",
        )}
      >
        {value.map((tag) => (
          <span key={tag} className="inline-flex items-center gap-1 rounded bg-zinc-100 py-0.5 pl-2 pr-1 font-mono text-xs text-zinc-800 ring-1 ring-inset ring-line">
            {tag}
            {!disabled && (
              <button
                type="button"
                aria-label={`Remove ${tag}`}
                onClick={() => onChange(value.filter((t) => t !== tag))}
                className="grid h-4 w-4 place-items-center rounded text-zinc-400 hover:bg-zinc-200 hover:text-zinc-700"
              >
                ×
              </button>
            )}
          </span>
        ))}
        <input
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          onBlur={() => draft.trim() && add(draft)}
          onPaste={(e) => {
            e.preventDefault();
            add(e.clipboardData.getData("text"));
          }}
          placeholder={value.length ? "" : placeholder}
          aria-label={ariaLabel}
          className="min-w-24 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-zinc-400"
        />
      </div>
      {!disabled && unused.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {unused.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => add(s)}
              className="rounded border border-dashed border-zinc-300 px-2 py-0.5 font-mono text-xs text-zinc-500 hover:border-brand-500 hover:text-brand-700"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
