import { useState, useCallback } from "react";
import { api, type ChatMessage, type ChatSession } from "@/lib/api";
import { generateId } from "@/lib/utils";

export function useChat(sessionId: string | undefined) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sending, setSending] = useState(false);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);

  const loadSessions = useCallback(async () => {
    const { sessions: s } = await api.listSessions();
    setSessions(s);
    setSessionsLoaded(true);
  }, []);

  const loadMessages = useCallback(async (id: string) => {
    const { messages: m } = await api.getSession(id);
    setMessages(m);
  }, []);

  const sendMessage = useCallback(
    async (content: string): Promise<ChatSession | null> => {
      if (!content.trim() || sending) return null;

      let activeSessionId = sessionId;

      // Create session if none active
      if (!activeSessionId) {
        const session = await api.createSession();
        activeSessionId = session.id;
        setSessions((prev) => [session, ...prev]);
      }

      // Optimistic user message
      const userMsg: ChatMessage = {
        id: generateId(),
        role: "user",
        content: content.trim(),
        timestamp: Date.now() / 1000,
      };
      setMessages((prev) => [...prev, userMsg]);
      setSending(true);

      try {
        const { reply } = await api.sendMessage(activeSessionId, content.trim());
        setMessages((prev) => [...prev, reply]);

        // Update session preview
        setSessions((prev) =>
          prev.map((s) =>
            s.id === activeSessionId
              ? {
                  ...s,
                  preview: reply.content.slice(0, 100),
                  updated_at: Date.now() / 1000,
                  message_count: s.message_count + 2,
                  title: s.title ?? content.trim().slice(0, 50),
                }
              : s,
          ),
        );

        // Return the session for navigation
        return sessions.find((s) => s.id === activeSessionId) ?? null;
      } finally {
        setSending(false);
      }
    },
    [sessionId, sending, sessions],
  );

  const deleteSession = useCallback(
    async (id: string) => {
      await api.deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (id === sessionId) setMessages([]);
    },
    [sessionId],
  );

  return {
    messages,
    sessions,
    sending,
    sessionsLoaded,
    loadSessions,
    loadMessages,
    sendMessage,
    deleteSession,
  };
}
