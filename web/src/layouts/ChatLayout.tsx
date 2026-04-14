import { useState, useEffect, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Menu, X, LogOut } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useChat } from "@/hooks/useChat";
import SessionList from "@/components/sidebar/SessionList";
import NewChatButton from "@/components/sidebar/NewChatButton";
import { cn } from "@/lib/utils";

interface Props {
  children: ReactNode;
}

export default function ChatLayout({ children }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const chat = useChat(sessionId);

  useEffect(() => {
    chat.loadSessions();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (sessionId) chat.loadMessages(sessionId);
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Close sidebar on mobile after navigation
  useEffect(() => {
    setSidebarOpen(false);
  }, [sessionId]);

  function handleNewChat() {
    navigate("/");
    setSidebarOpen(false);
  }

  function handleSelectSession(id: string) {
    navigate(`/c/${id}`);
  }

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div className="flex h-dvh overflow-hidden bg-background text-foreground">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-border bg-card transition-transform duration-200 md:static md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {/* Sidebar header */}
        <div className="flex h-14 items-center justify-between border-b border-border px-4">
          <span className="text-sm font-semibold tracking-wide uppercase opacity-70">
            Birkin
          </span>
          <button
            onClick={() => setSidebarOpen(false)}
            className="rounded p-1 transition-colors hover:bg-accent md:hidden"
            aria-label="Close sidebar"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* New chat */}
        <div className="p-3">
          <NewChatButton onClick={handleNewChat} />
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto">
          <SessionList
            sessions={chat.sessions}
            activeId={sessionId}
            onSelect={handleSelectSession}
            onDelete={chat.deleteSession}
          />
        </div>

        {/* User info */}
        <div className="border-t border-border p-3">
          <div className="flex items-center justify-between">
            <span className="truncate text-sm text-muted-foreground">
              {user?.username}
            </span>
            <button
              onClick={handleLogout}
              className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              aria-label="Log out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex flex-1 flex-col overflow-hidden">
        {/* Mobile header */}
        <header className="flex h-14 items-center border-b border-border px-4 md:hidden">
          <button
            onClick={() => setSidebarOpen(true)}
            className="rounded p-1.5 transition-colors hover:bg-accent"
            aria-label="Open sidebar"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="ml-3 text-sm font-semibold tracking-wide uppercase opacity-70">
            Birkin
          </span>
        </header>

        {children}
      </main>
    </div>
  );
}
