import type { ReactNode } from "react";

interface AdminCardProps {
  children: ReactNode;
  className?: string;
  description?: string;
  title?: string;
}

export function AdminCard({
  children,
  className = "",
  description,
  title,
}: AdminCardProps) {
  return (
    <section
      className={`rounded-3xl border border-black/5 bg-white p-6 shadow-[0_10px_35px_rgba(0,0,0,0.035)] sm:p-8 ${className}`}
    >
      {title ? <h2 className="text-lg font-semibold tracking-tight text-neutral-950">{title}</h2> : null}
      {description ? <p className="mt-2 text-sm leading-6 text-neutral-500">{description}</p> : null}
      <div className={title || description ? "mt-6" : ""}>{children}</div>
    </section>
  );
}
