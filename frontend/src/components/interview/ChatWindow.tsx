import type { ReactNode } from "react";

interface ChatWindowProps {
  children: ReactNode;
  composer: ReactNode;
}

export function ChatWindow({ children, composer }: ChatWindowProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {children}
      {composer}
    </div>
  );
}
