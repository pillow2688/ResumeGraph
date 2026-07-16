import type { ReactNode } from "react";

interface InterviewLayoutProps {
  sidebar: ReactNode;
  header: ReactNode;
  children: ReactNode;
  citationDrawer: ReactNode;
}

export function InterviewLayout({
  sidebar,
  header,
  children,
  citationDrawer,
}: InterviewLayoutProps) {
  return (
    <main className="h-[100dvh] overflow-hidden bg-stone-100 text-slate-950">
      <div className="grid h-full lg:grid-cols-[18rem_minmax(0,1fr)]">
        {sidebar}
        <section className="flex min-w-0 flex-col bg-stone-50">
          {header}
          {children}
        </section>
      </div>
      {citationDrawer}
    </main>
  );
}
