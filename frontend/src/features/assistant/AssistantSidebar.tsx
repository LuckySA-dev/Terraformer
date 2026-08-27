import { Bot, X } from 'lucide-react';
import { AssistantChatPanel } from './AssistantChatPanel';

interface AssistantSidebarProps {
  onClose: () => void;
  onOpenInventory?: (() => void) | undefined;
}

/**
 * The assistant's own right rail.
 *
 * It shares the column with the device inspector and the two are mutually
 * exclusive, so the chat gets the full height rather than the tab-sized slice
 * it had inside the inspector. Which devices it is about is chosen inside the
 * conversation instead of being fixed by where it was opened from.
 */
export function AssistantSidebar({ onClose, onOpenInventory }: AssistantSidebarProps) {
  return (
    <aside className="inspector inspector--assistant" aria-label="Assistant">
      <header className="inspector__header">
        <div className="device-avatar">
          <Bot size={20} />
        </div>
        <div className="inspector__identity">
          <span>ASSISTANT</span>
          <h2>Ask about your network</h2>
          <div>
            <span className="mono">Read-only tools · changes need your review</span>
          </div>
        </div>
        <button
          type="button"
          className="icon-button inspector__close"
          onClick={onClose}
          aria-label="Close assistant"
        >
          <X size={16} />
        </button>
      </header>
      <div className="inspector__content inspector__content--flush">
        <AssistantChatPanel
          scopeHint="Pick the devices you want this chat to be about, or leave it on All. The assistant can read facts, interfaces, neighbors, snapshots and events, and draft a Change Plan for you to review."
          {...(onOpenInventory === undefined ? {} : { onOpenInventory })}
        />
      </div>
    </aside>
  );
}
