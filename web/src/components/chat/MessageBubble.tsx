import { User, Sparkles } from "lucide-react";
import type { ChatMessage } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  message: ChatMessage;
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn(
        "flex gap-3",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
      style={{ animation: "fade-in 200ms ease-out" }}
    >
      {/* Avatar */}
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-foreground/10" : "bg-accent",
        )}
      >
        {isUser ? (
          <User className="h-4 w-4 text-foreground/60" />
        ) : (
          <Sparkles className="h-4 w-4 text-foreground/60" />
        )}
      </div>

      {/* Content */}
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-foreground/10 text-foreground"
            : "bg-card text-card-foreground border border-border",
        )}
      >
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
      </div>
    </div>
  );
}
