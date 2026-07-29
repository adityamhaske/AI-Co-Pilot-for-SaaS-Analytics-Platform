import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { IconButton } from "@/components/ui/primitives";
import { SendIcon, StopIcon } from "@/components/ui/icons";

const MAX_LENGTH = 4000;
const MIN_HEIGHT = 24;   // one line of text
const MAX_HEIGHT = 200;  // roughly eight lines, then it scrolls

/**
 * The question box.
 *
 * Grows with its content up to a ceiling, submits on Enter (Shift+Enter for a newline),
 * and turns into a stop control while a response is streaming — cancelling is a normal
 * action, not an edge case.
 */
export function Composer({
  onSubmit,
  onCancel,
  busy,
  autoFocus,
}: {
  onSubmit: (text: string) => void;
  onCancel: () => void;
  busy: boolean;
  autoFocus?: boolean;
}) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Grow to fit, then scroll.
  //
  // Two details make this reliable. Collapsing to 0 before measuring gives the content
  // height rather than the current box height. And the measurement is repeated after a
  // paint: on the very first pass the stylesheet may not be applied yet, and because
  // `value` has not changed there would be nothing to trigger a correction — the empty
  // box stayed stuck at its maximum height.
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;

    const resize = () => {
      el.style.height = "0px";
      el.style.height = `${Math.min(
        Math.max(el.scrollHeight, MIN_HEIGHT),
        MAX_HEIGHT
      )}px`;
    };

    resize();
    const frame = requestAnimationFrame(resize);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  // Return focus to the box once a response finishes, so the next question is typeable.
  useEffect(() => {
    if (!busy) textareaRef.current?.focus();
  }, [busy]);

  const submit = () => {
    const text = value.trim();
    if (!text || busy) return;
    onSubmit(text);
    setValue("");
  };

  const remaining = MAX_LENGTH - value.length;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="relative"
    >
      <div className="flex items-end gap-2 rounded-lg border border-line bg-surface p-2 shadow-raised transition-colors focus-within:border-accent focus-within:ring-1 focus-within:ring-accent">
        <label htmlFor="composer" className="sr-only">
          Ask a question about your metrics
        </label>
        <textarea
          id="composer"
          ref={textareaRef}
          rows={1}
          value={value}
          autoFocus={autoFocus}
          maxLength={MAX_LENGTH}
          placeholder="Ask about MRR, churn, active users…"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          style={{ maxHeight: MAX_HEIGHT }}
          className="flex-1 resize-none overflow-y-auto bg-transparent px-2 py-1.5 text-base text-ink outline-none placeholder:text-ink-muted"
        />

        {busy ? (
          <IconButton
            label="Stop generating"
            onClick={onCancel}
            className="bg-surface-hover text-ink hover:bg-surface-active"
          >
            <StopIcon />
          </IconButton>
        ) : (
          <IconButton
            label="Send question"
            type="submit"
            disabled={!value.trim()}
            className="bg-accent text-accent-ink hover:bg-accent-hover hover:text-accent-ink disabled:bg-surface-active disabled:text-ink-muted"
          >
            <SendIcon />
          </IconButton>
        )}
      </div>

      <div className="mt-1.5 flex items-center justify-between px-1">
        <p className="text-2xs text-ink-muted">
          <kbd className="font-sans font-medium">Enter</kbd> to send ·{" "}
          <kbd className="font-sans font-medium">Shift+Enter</kbd> for a new line
        </p>
        {remaining < 500 && (
          <p
            className={`text-2xs tabular-nums ${
              remaining < 50 ? "text-danger" : "text-ink-muted"
            }`}
          >
            {remaining} left
          </p>
        )}
      </div>
    </form>
  );
}
