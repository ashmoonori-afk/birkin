import { Sparkles } from "lucide-react";

export default function TypingIndicator() {
  return (
    <div className="flex gap-3" style={{ animation: "fade-in 200ms ease-out" }}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent">
        <Sparkles className="h-4 w-4 text-foreground/60" />
      </div>
      <div className="flex items-center gap-1.5 rounded-2xl border border-border bg-card px-4 py-3">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="block h-2 w-2 rounded-full bg-muted-foreground"
            style={{
              animation: `pulse-dot 1.4s ease-in-out ${i * 0.2}s infinite`,
            }}
          />
        ))}
      </div>
    </div>
  );
}
