"use client";
import { useActionState } from "react";
import { login, type FormState } from "@/app/admin/actions";
import { Icon } from "@/components/ui/Icon";

export function LoginForm() {
  const [state, action, pending] = useActionState<FormState, FormData>(login, null);
  return (
    <form action={action} className="space-y-4">
      <div>
        <label htmlFor="password" className="label mb-1.5 block">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          required
          autoComplete="current-password"
          autoFocus
          className="field"
          aria-describedby={state && !state.ok ? "login-error" : undefined}
          aria-invalid={state && !state.ok ? true : undefined}
        />
      </div>
      {state && !state.ok && (
        <p id="login-error" role="alert" className="flex items-start gap-2 text-sm text-danger">
          <Icon name="warning" size={16} className="mt-0.5 shrink-0" />
          {state.message}
        </p>
      )}
      <button type="submit" className="btn btn-primary w-full" disabled={pending}>
        <Icon name="lock" size={16} />
        {pending ? "Checking…" : "Sign in"}
      </button>
      <p className="text-xs leading-relaxed text-ink-3">Sessions last 12 hours. Five wrong attempts lock this address out for 15 minutes.</p>
    </form>
  );
}
