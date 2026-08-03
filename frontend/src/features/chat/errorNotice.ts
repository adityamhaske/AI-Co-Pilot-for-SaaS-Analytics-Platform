/**
 * How a stopped turn should read, given why it stopped.
 *
 * Every error used to render as one red box, which put "the answer above is incomplete,
 * ask something narrower" in the same visual language as "nothing worked". A reader
 * cannot act on the first if it looks like the second: one is an invitation to rephrase a
 * question that partly succeeded, the other is a dead end.
 *
 * Its own module rather than a second export from MessageList, which breaks Fast Refresh.
 */

/** Mirrors the `kind` field on the backend's SSE error event. */
export type ErrorKind = "provider" | "internal" | "step_limit" | "timeout";

export interface ErrorNotice {
  tone: "warning" | "danger";
  label: string;
  hint: string | null;
}

export function noticeFor(kind: ErrorKind | undefined): ErrorNotice {
  switch (kind) {
    case "step_limit":
    case "timeout":
      // A real answer is sitting above this one. Warn; do not alarm.
      return {
        tone: "warning",
        label: kind === "timeout" ? "Stopped early" : "Reached the step limit",
        hint: "The answer above may be incomplete. A narrower question usually finishes.",
      };
    case "provider":
      return { tone: "danger", label: "Model provider unavailable", hint: null };
    default:
      // Includes `internal` and an absent kind — an older server, or a field we do not
      // recognise. Treating the unknown as a failure is the safe direction: it is worse
      // to soften a real error than to over-report a partial one.
      return { tone: "danger", label: "Something went wrong", hint: null };
  }
}
