import { useState } from "react";

import { SparkIcon } from "@/components/ui/icons";
import { Banner, Button, Field, Input, Spinner } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";

export function LoginPage({ onSignIn }: { onSignIn: (token: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const { access_token } = await api.login(email, password);
      onSignIn(access_token);
    } catch (err) {
      // The server returns the same message for an unknown email and a wrong
      // password; the UI must not add a distinction the backend deliberately avoids.
      setError(
        err instanceof ApiError
          ? err.status === 401
            ? "Incorrect email or password."
            : err.friendlyMessage
          : "Could not reach the server."
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-sunken px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-accent text-accent-ink">
            <SparkIcon className="h-6 w-6" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">
            Analytics Co-pilot
          </h1>
          <p className="mt-1.5 text-sm text-ink-secondary">
            Sign in to ask questions about your SaaS metrics.
          </p>
        </div>

        <div className="rounded-lg border border-line bg-surface p-6 shadow-raised">
          <form onSubmit={submit} className="space-y-4" noValidate>
            {error && <Banner onDismiss={() => setError(null)}>{error}</Banner>}

            <Field id="email" label="Email">
              <Input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                aria-invalid={Boolean(error)}
                placeholder="you@company.com"
              />
            </Field>

            <Field id="password" label="Password">
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={Boolean(error)}
                placeholder="••••••••"
              />
            </Field>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              disabled={busy || !email || !password}
              className="w-full"
            >
              {busy ? (
                <>
                  <Spinner className="h-4 w-4" />
                  Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </Button>
          </form>
        </div>

        <p className="mt-5 text-center text-xs leading-relaxed text-ink-muted">
          This is a demonstration running on synthetic data. Accounts are created by the
          seed script — there is no public sign-up.
        </p>
      </div>
    </main>
  );
}
