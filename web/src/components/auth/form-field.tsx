import type { ComponentProps } from "react";

type FormFieldProps = ComponentProps<"input"> & {
  hint?: string;
  label: string;
};

export function FormField({
  "aria-describedby": describedBy,
  hint,
  id,
  label,
  ...props
}: FormFieldProps) {
  const hintId = hint && id ? `${id}-hint` : undefined;
  const descriptionIds = [describedBy, hintId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="space-y-1.5">
      <label className="block font-medium" htmlFor={id}>
        {label}
      </label>
      <input
        aria-describedby={descriptionIds}
        className="h-11 w-full rounded-lg border bg-background px-3 text-sm outline-none transition-[border-color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-60"
        id={id}
        {...props}
      />
      {hint ? (
        <p className="text-xs leading-5 text-muted-foreground" id={hintId}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
