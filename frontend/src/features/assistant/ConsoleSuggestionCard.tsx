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
  const [copyFailed, setCopyFailed] = useState(false);
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
              setCopyFailed(false);
              try {
                // Only a blocklist rejection may show the "withheld" notice.
                // Folding a clipboard failure in here too would tell the
                // operator a harmless command matched a destructive pattern.
                await api.stageCommand(sessionId, command);
              } catch {
                setWithheld(true);
                setChecking(false);
                return;
              }
              try {
                await navigator.clipboard.writeText(command);
                setCopied(true);
              } catch {
                setCopyFailed(true);
              } finally {
                setChecking(false);
              }
              onOpenInventory();
            }}
          >
            Copy and open Inventory
          </Button>
          {copied ? (
            <span className="mini-result mini-result--success" role="status">
              Copied -- select the device and paste it into its terminal.
            </span>
          ) : null}
          {copyFailed ? (
            <span className="mini-result" role="status">
              This browser blocked the clipboard. The command passed its safety check -- copy it
              from above by hand.
            </span>
          ) : null}
        </div>
      )}
    </div>
  );
}
