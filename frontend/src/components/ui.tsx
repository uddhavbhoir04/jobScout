import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

export function cn(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ surfaces */

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn("rounded-lg border border-line bg-surface", className)}>{children}</section>;
}

export function CardHeader({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-3.5">
      <div className="min-w-0">
        <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs leading-5 text-zinc-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

/** Title block at the top of every page: what this page is for, plus its main actions. */
export function PageHeader({
  title,
  description,
  actions,
  meta,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-4 border-b border-line pb-5">
      <div className="min-w-0 max-w-2xl">
        <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.01em] text-ink">{title}</h1>
        {description && <p className="mt-1.5 text-sm leading-6 text-zinc-500">{description}</p>}
      </div>
      {(actions || meta) && (
        <div className="flex flex-wrap items-center gap-3">
          {meta}
          {actions}
        </div>
      )}
    </header>
  );
}

/** Row of numbers with labels, separated by hairlines. */
export function StatRow({ items, className }: { items: { label: string; value: ReactNode; hint?: string; accent?: boolean }[]; className?: string }) {
  return (
    <dl className={cn("grid divide-x divide-line overflow-hidden rounded-lg border border-line bg-surface", className)}
        style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
      {items.map((s) => (
        <div key={s.label} className="min-w-0 px-4 py-3">
          <dt className="truncate text-xs text-zinc-500" title={s.hint}>{s.label}</dt>
          <dd className={cn("mt-1 truncate text-lg font-semibold tabular-nums", s.accent ? "text-brand-700" : "text-ink")}>{s.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-3 h-9 w-9 rounded-md border border-dashed border-zinc-300" aria-hidden />
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <p className="mt-1 max-w-sm text-sm leading-6 text-zinc-500">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ controls */

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
};

export function buttonClass(variant: ButtonProps["variant"] = "secondary", size: ButtonProps["size"] = "md") {
  return cn(
    "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors",
    "disabled:cursor-not-allowed disabled:opacity-50",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500",
    size === "sm" ? "h-8 px-3 text-[13px]" : "h-9 px-3.5 text-sm",
    variant === "primary" && "bg-brand-700 text-white hover:bg-brand-800 active:bg-brand-900",
    variant === "secondary" && "border border-line bg-surface text-zinc-800 hover:border-zinc-300 hover:bg-zinc-50",
    variant === "ghost" && "text-zinc-600 hover:bg-zinc-100 hover:text-ink",
    variant === "danger" && "border border-red-200 bg-surface text-red-700 hover:bg-red-50",
  );
}

export function Button({ variant = "secondary", size = "md", className, ...props }: ButtonProps) {
  return <button {...props} className={cn(buttonClass(variant, size), className)} />;
}

const fieldClass = cn(
  "w-full rounded-md border border-line bg-surface text-sm text-ink placeholder:text-zinc-400",
  "transition-colors hover:border-zinc-300 focus:border-brand-500 focus:outline-none focus:ring-3 focus:ring-brand-100",
  "disabled:cursor-not-allowed disabled:bg-zinc-50 read-only:bg-zinc-50",
);

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(fieldClass, "h-9 px-3", props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(fieldClass, "resize-y px-3 py-2 leading-6", props.className)} />;
}

export function Label({ children, hint, htmlFor }: { children: ReactNode; hint?: ReactNode; htmlFor?: string }) {
  return (
    <div className="mb-1.5 flex items-baseline justify-between gap-3">
      <label htmlFor={htmlFor} className="text-[13px] font-medium text-zinc-800">{children}</label>
      {hint && <span className="text-xs text-zinc-500">{hint}</span>}
    </div>
  );
}

/* ------------------------------------------------------------------ status */

const TONES = {
  neutral: { box: "bg-zinc-100 text-zinc-600", dot: "bg-zinc-400" },
  green: { box: "bg-emerald-50 text-emerald-800", dot: "bg-emerald-600" },
  amber: { box: "bg-amber-50 text-amber-800", dot: "bg-amber-600" },
  red: { box: "bg-red-50 text-red-800", dot: "bg-red-600" },
  blue: { box: "bg-sky-50 text-sky-800", dot: "bg-sky-600" },
};
export type Tone = keyof typeof TONES;

export function Badge({ tone = "neutral", children, dot = true }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-xs font-medium", TONES[tone].box)}>
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full", TONES[tone].dot)} aria-hidden />}
      {children}
    </span>
  );
}

export function emailStatusTone(status: string | null): Tone {
  switch (status) {
    case "sent":
    case "replied":
      return "green";
    case "drafted":
    case "sending":
      return "blue";
    case "failed":
    case "bounced":
      return "red";
    case "pending":
      return "amber";
    default:
      return "neutral";
  }
}

const NOTICE = {
  info: "border-line bg-zinc-50 text-zinc-700",
  success: "border-brand-200 bg-brand-50 text-brand-800",
  warning: "border-amber-600/20 bg-amber-50 text-amber-800",
  error: "border-red-200 bg-red-50 text-red-800",
};

export function Notice({ tone = "info", children, className }: { tone?: keyof typeof NOTICE; children: ReactNode; className?: string }) {
  return <div className={cn("rounded-md border px-3 py-2 text-[13px] leading-5", NOTICE[tone], className)}>{children}</div>;
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return <Notice tone="error">{message}</Notice>;
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn("inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-700", className)}
    />
  );
}

/** Small segmented control (tabs / filters). */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="tablist" className="inline-flex flex-wrap rounded-md border border-line bg-zinc-100/70 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-[5px] px-3 py-1 text-[13px] transition-colors",
            value === o.value ? "bg-surface font-medium text-ink shadow-[0_1px_1px_rgb(31_30_27/0.06)] ring-1 ring-line" : "text-zinc-600 hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
