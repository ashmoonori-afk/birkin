async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem("birkin_token");
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (init?.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(url, { ...init, headers });

  if (res.status === 401) {
    localStorage.removeItem("birkin_token");
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }

  return res.json();
}

// ── Types ──

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

export interface ChatSession {
  id: string;
  title: string | null;
  created_at: number;
  updated_at: number;
  message_count: number;
  preview: string | null;
}

export interface User {
  id: string;
  username: string;
}

// ── API ──

export const api = {
  // Auth
  login: (username: string, password: string) =>
    fetchJSON<{ token: string; user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  me: () => fetchJSON<User>("/api/auth/me"),

  // Chat sessions
  listSessions: () =>
    fetchJSON<{ sessions: ChatSession[] }>("/api/chat/sessions"),

  createSession: () =>
    fetchJSON<ChatSession>("/api/chat/sessions", { method: "POST" }),

  getSession: (id: string) =>
    fetchJSON<{ session: ChatSession; messages: ChatMessage[] }>(
      `/api/chat/sessions/${encodeURIComponent(id)}`,
    ),

  deleteSession: (id: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/chat/sessions/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),

  // Chat messages
  sendMessage: (sessionId: string, content: string) =>
    fetchJSON<{ message: ChatMessage; reply: ChatMessage }>(
      `/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ content }),
      },
    ),
};
