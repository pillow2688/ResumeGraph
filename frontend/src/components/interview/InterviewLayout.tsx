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
    <main className="h-screen h-[100dvh] overflow-hidden bg-neutral-100 text-neutral-950">
      <div className="grid h-full min-h-0 lg:grid-cols-[18rem_minmax(0,1fr)]">
        {sidebar}
        <section className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-neutral-50">
          {header}
          {children}
        </section>
      </div>
      {citationDrawer}
    </main>
  );
}
