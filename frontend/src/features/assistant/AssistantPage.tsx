import { AssistantChatPanel } from './AssistantChatPanel';

/**
 * The Assistant tab is the chat itself.
 *
 * It used to be a provider-key screen that told you the chat lived somewhere
 * else, which meant the sidebar entry named after the assistant was the one
 * place you could not talk to it. Keys now sit behind the model picker in the
 * composer, so the rare action stays reachable without occupying the page.
 */
export function AssistantPage() {
  return (
    <main className="assistant-page">
      <AssistantChatPanel
        scopeHint="This chat spans the whole workspace, so you can ask it to compare devices or reason across the topology. It is kept separate from the per-device conversations in each device's Assistant tab. Ask it to look a device up by name and it will find the right one."
      />
    </main>
  );
}
