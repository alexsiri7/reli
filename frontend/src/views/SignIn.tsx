import { useState } from "react";

import { signInUrl } from "../api";

/**
 * What the callback's `/?error=` codes mean, in the sign-in view's own words. Codes rather than
 * server text, so nothing in the URL can put a sentence of its choosing on this page.
 */
const ERRORS: Record<string, string> = {
  invite_only: "This Reli is invite-only: sign in with the Google account listed in ALLOWED_EMAILS on the deploy.",
  cancelled: "Google sign-in was cancelled.",
};

function errorMessage(code: string | null): string | null {
  if (code === null) return null;
  return ERRORS[code] ?? `Sign-in did not complete (${code}).`;
}

/** The whole app while there is no session: one button, and why the last attempt did not work. */
export function SignIn() {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(
    errorMessage(new URLSearchParams(window.location.search).get("error")),
  );

  function start() {
    setStarting(true);
    setError(null);
    signInUrl()
      .then((url) => window.location.assign(url))
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : String(reason));
        setStarting(false);
      });
  }

  return (
    <section className="sign-in">
      <h1>Sign in</h1>
      <p className="lede">Reli is the owner's graph. Sign in with the Google account allowed on this deploy.</p>
      <button className="google" onClick={start} disabled={starting}>
        {starting ? "Opening Google…" : "Sign in with Google"}
      </button>
      {error !== null && <p className="status error">{error}</p>}
    </section>
  );
}
