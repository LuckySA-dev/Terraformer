import { useState } from 'react';
import { api } from '../../api/network';
import { Button } from '../../components/ui/Button';

interface ConsoleSuggestionCardProps {
  command: string;
  sessionId: string;
  onOpenInventory: () => void;
}

export function ConsoleSuggestionCard({ command, sessionId, onOpenInventory }: ConsoleSuggestionCardProps) {
  const [withheld, setWithheld] = useState(false);
  const [copied, setCopied] = useState(false);
  const [checking, setChecking] = useState(false);

  return (
    <div className="console-suggestion">
      <pre>{command}</pre>
      {withheld ? (
        <p className="form-error" role="alert">
          This command was withheld because it matches a blocked pattern
          (erase/reload/format/factory-reset). Direct Mode itself still lets you type it manually if
          you choose to.
        </p>
      ) : (
        <div className="console-suggestion__actions">
          <Button
            busy={checking}
            onClick={async () => {
              setChecking(true);
              try {
                await api.stageCommand(sessionId, command);
                await navigator.clipboard.writeText(command);
                setCopied(true);
                onOpenInventory();
              } catch {
                setWithheld(true);
              } finally {
                setChecking(false);
              }
            }}
          >
            Copy and open Inventory
          </Button>
          {copied ? (
            <span className="mini-result mini-result--success" role="status">
              Copied -- select the device and paste it into its terminal.
            </span>
          ) : null}
        </div>
      )}
    </div>
  );
}
