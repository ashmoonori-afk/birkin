import { Plus } from "lucide-react";

interface Props {
  onClick: () => void;
}

export default function NewChatButton({ onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      aria-label="New conversation"
    >
      <Plus className="h-4 w-4" />
      <span>New chat</span>
    </button>
  );
}
