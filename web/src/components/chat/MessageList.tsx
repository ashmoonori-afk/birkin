import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/api";
import MessageBubble from "./MessageBubble";
import TypingIndicator from "./TypingIndicator";

interface Props {
  messages: ChatMessage[];
  sending: boolean;
}

export default function MessageList({ messages, sending }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, sending]);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-6">
        {messages.length === 0 && (
          <p className="py-20 text-center text-sm text-muted-foreground">
            No messages yet. Start the conversation below.
          </p>
        )}

        <div className="space-y-6">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          {sending && <TypingIndicator />}
        </div>

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
