import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/hooks/useAuth";
import ChatLayout from "@/layouts/ChatLayout";
import ChatPage from "@/pages/ChatPage";
import LoginPage from "@/pages/LoginPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <ChatLayout>
              <Routes>
                <Route index element={<ChatPage />} />
                <Route path="c/:sessionId" element={<ChatPage />} />
              </Routes>
            </ChatLayout>
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <div className="noise-overlay" />
      <AppRoutes />
    </AuthProvider>
  );
}
