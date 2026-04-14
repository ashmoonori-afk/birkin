import { useParams, useNavigate } from "react-router-dom";
import { useChat } from "@/hooks/useChat";
import MessageList from "@/components/chat/MessageList";
import ChatInput from "@/components/chat/ChatInput";
import { Sparkles } from "lucide-react";

export default function ChatPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const chat = useChat(sessionId);

  async function handleSend(content: string) {
    const session = await chat.sendMessage(content);
    // Navigate to session URL if this was a new chat
    if (!sessionId && session) {
      navigate(`/c/${session.id}`, { replace: true });
    }
  }

  const isEmpty = chat.messages.length === 0 && !sessionId;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {isEmpty ? (
        /* Empty state — new conversation prompt */
        <div className="flex flex-1 flex-col items-center justify-center px-6">
          <div className="mb-8 flex h-16 w-16 items-center justify-center rounded-2xl bg-accent">
            <Sparkles className="h-8 w-8 text-foreground opacity-60" />
          </div>
          <h1 className="mb-2 text-2xl font-semibold tracking-tight">
            How can I help?
          </h1>
          <p className="mb-8 max-w-md text-center text-sm text-muted-foreground">
            Start a conversation with Birkin. Ask questions, get help with tasks,
            or just chat.
          </p>
          <div className="w-full max-w-2xl">
            <ChatInput onSend={handleSend} sending={chat.sending} autoFocus />
          </div>
        </div>
      ) : (
        /* Active conversation */
        <>
          <MessageList messages={chat.messages} sending={chat.sending} />
          <div className="border-t border-border px-4 py-3">
            <div className="mx-auto max-w-3xl">
              <ChatInput onSend={handleSend} sending={chat.sending} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
