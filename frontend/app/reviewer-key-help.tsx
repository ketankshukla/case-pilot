"use client";

import { useState } from "react";

export function ReviewerKeyHelp({ command }: { command: string }) {
  const [feedback, setFeedback] = useState("");

  async function copyCommand() {
    try {
      await navigator.clipboard.writeText(command);
      setFeedback("Command copied.");
    } catch {
      setFeedback("Select and copy the command above.");
    }
  }

  return (
    <div className="review-key-help" id="reviewer-key-help">
      <p><strong>1. Open the key file.</strong> Run this command in PowerShell to open it in Notepad.</p>
      <code className="review-key-command">{command}</code>
      <div className="review-key-copy">
        <button type="button" onClick={copyCommand}>Copy command</button>
        <span role="status">{feedback}</span>
      </div>
      <p><strong>2. Copy the key.</strong> In Notepad, find <code>CASEPILOT_REVIEWER_TOKEN=</code> and paste the text after the equals sign into the field below.</p>
    </div>
  );
}
