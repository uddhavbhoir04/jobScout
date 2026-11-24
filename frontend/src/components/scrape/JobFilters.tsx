"use client";

import { cn, Input, Label } from "../ui";

// Filters on what a job post asks for, shared by the LinkedIn and Telegram panels.
// Rules (the backend enforces them too): a post's experience may not go above the max; with a location set,
// the post must mention one of them unless it's remote. Posts that don't mention experience or work type are kept.

export type WorkType = "remote" | "hybrid" | "on-site";

export type JobFilterValues = {
  expMin: string; // "" = no minimum
  expMax: string; // "" = no maximum
  location: string; // comma-separated, any one matches; "" = anywhere
  workTypes: WorkType[]; // empty = any
};

export const DEFAULT_JOB_FILTERS: JobFilterValues = { expMin: "", expMax: "", location: "", workTypes: [] };

const WORK_TYPES: { value: WorkType; label: string }[] = [
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "on-site", label: "On-site" },
];

const years = (v: string) => (v === "" ? null : Number(v));

export function experienceInvalid(f: JobFilterValues) {
  const lo = years(f.expMin);
  const hi = years(f.expMax);
  return lo !== null && hi !== null && lo > hi;
}

/** The request-body fields the backend's ScrapeIn expects. */
export function jobFilterParams(f: JobFilterValues) {
  return {
    exp_min: years(f.expMin),
    exp_max: years(f.expMax),
    location: f.location.trim() || null,
    work_types: f.workTypes,
  };
}

export function JobFilterFields({
  value,
  onChange,
  disabled,
}: {
  value: JobFilterValues;
  onChange: (patch: Partial<JobFilterValues>) => void;
  disabled?: boolean;
}) {
  const toggleType = (t: WorkType) =>
    onChange({ workTypes: value.workTypes.includes(t) ? value.workTypes.filter((x) => x !== t) : [...value.workTypes, t] });

  return (
    <>
      <div>
        <Label hint="Optional">Experience (years)</Label>
        <div className="flex items-center gap-2">
          <Input type="number" min={0} max={50} placeholder="Min" aria-label="Minimum years" value={value.expMin}
            disabled={disabled} onChange={(e) => onChange({ expMin: e.target.value })} className="w-20" />
          <span className="text-xs text-zinc-500">to</span>
          <Input type="number" min={0} max={50} placeholder="Max" aria-label="Maximum years" value={value.expMax}
            disabled={disabled} onChange={(e) => onChange({ expMax: e.target.value })} className="w-20" />
        </div>
        {experienceInvalid(value) ? (
          <p className="mt-1.5 text-xs text-red-700">Minimum can&apos;t be more than maximum.</p>
        ) : (
          <p className="mt-1.5 text-xs text-zinc-500">Posts asking for more than the max are skipped. Posts that don&apos;t mention experience are kept.</p>
        )}
      </div>

      <div>
        <Label hint="Optional">Work location</Label>
        <Input
          value={value.location}
          disabled={disabled}
          maxLength={200}
          placeholder="Pune, Bangalore"
          aria-label="Work location"
          onChange={(e) => onChange({ location: e.target.value })}
        />
        <p className="mt-1.5 text-xs text-zinc-500">Comma-separated. A post must mention at least one, unless it&apos;s remote.</p>
      </div>

      <div>
        <Label hint={value.workTypes.length ? undefined : "Any"}>Work type</Label>
        <div className="grid grid-cols-3 gap-1.5">
          {WORK_TYPES.map(({ value: t, label }) => {
            const on = value.workTypes.includes(t);
            return (
              <button
                key={t}
                type="button"
                aria-pressed={on}
                disabled={disabled}
                onClick={() => toggleType(t)}
                className={cn(
                  "h-8 rounded-md border text-[13px] transition-colors disabled:opacity-60",
                  on
                    ? "border-brand-600 bg-brand-50 font-medium text-brand-800"
                    : "border-line bg-surface text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50",
                )}
              >
                {label}
              </button>
            );
          })}
        </div>
        <p className="mt-1.5 text-xs text-zinc-500">Pick any number. Posts that don&apos;t say are kept.</p>
      </div>
    </>
  );
}
