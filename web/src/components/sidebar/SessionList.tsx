import { MessageSquare, Trash2 } from "lucide-react";
import type { ChatSession } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";

interface Props {
  sessions: ChatSession[];
  activeId: string | undefined;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

export default function SessionList({
  sessions,
  activeId,
  onSelect,
  onDelete,
}: Props) {
  if (sessions.length === 0) {
    return (
      <p className="px-4 py-8 text-center text-xs text-muted-foreground">
        No conversations yet
      </p>
    );
  }

  return (
    <nav className="space-y-0.5 px-2" aria-label="Conversations">
      {sessions.map((session) => (
        <div
          key={session.id}
          className={cn(
            "group relative flex cursor-pointer items-start gap-2.5 rounded-lg px-3 py-2.5 transition-colors",
            session.id === activeId
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
          )}
          onClick={() => onSelect(session.id)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && onSelect(session.id)}
          aria-current={session.id === activeId ? "page" : undefined}
        >
          <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 opacity-50" />

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {session.title ?? "New conversation"}
            </p>
            {session.preview && (
              <p className="mt-0.5 truncate text-xs opacity-60">
                {session.preview}
              </p>
            )}
            <p className="mt-1 text-[0.65rem] uppercase tracking-wider opacity-40">
              {timeAgo(session.updated_at)}
            </p>
          </div>

          {/* Delete button — visible on hover */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(session.id);
            }}
            className="absolute right-2 top-2.5 hidden rounded p-1 text-muted-foreground transition-colors hover:bg-destructive/20 hover:text-destructive group-hover:block"
            aria-label={`Delete ${session.title ?? "conversation"}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </nav>
  );
}
