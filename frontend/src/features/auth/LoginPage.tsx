import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useNavigate } from "react-router-dom";

import { ApiError, type LoginRequest, login, type Session } from "../../api/client";

type LoginPageProps = { session: Session | undefined };

export function LoginPage({ session }: LoginPageProps): ReactNode {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const errorId = useId();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginRequest>();
  const mutation = useMutation({
    mutationFn: (credentials: LoginRequest) => login(credentials),
    onSuccess: (authenticated) => {
      queryClient.setQueryData(["session"], authenticated);
      navigate("/crm/inquiries", { replace: true });
    },
  });

  if (session) return <Navigate replace to="/crm/inquiries" />;
  const unavailable = mutation.error instanceof ApiError && mutation.error.retryable;

  return (
    <main className="login-page" id="main-content">
      <section className="login-intro" aria-labelledby="login-heading">
        <p className="eyebrow">Private workspace</p>
        <h1 id="login-heading">Team sign in</h1>
        <p>Review new property enquiries and keep every follow-up with the right person.</p>
        <div className="privacy-note">
          <strong>Customer information stays private.</strong>
          <span>Use only your assigned team account. Never share credentials.</span>
        </div>
      </section>
      <form
        className="login-card"
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
        noValidate
      >
        <h2>Welcome back</h2>
        <p>Enter your work email and password.</p>
        {mutation.isError && (
          <div className="form-alert" id={errorId} role="alert">
            {unavailable
              ? "Sign in is temporarily unavailable. Please try again."
              : "Email or password wasn’t recognised. Check both and try again."}
          </div>
        )}
        <label htmlFor="login-email">Email</label>
        <input
          id="login-email"
          type="email"
          autoComplete="username"
          maxLength={254}
          aria-invalid={Boolean(errors.email)}
          {...register("email", { required: "Enter your email address." })}
        />
        {errors.email && <span className="field-error">{errors.email.message}</span>}
        <label htmlFor="login-password">Password</label>
        <input
          id="login-password"
          type="password"
          autoComplete="current-password"
          maxLength={128}
          aria-invalid={Boolean(errors.password)}
          aria-describedby={mutation.isError ? errorId : undefined}
          {...register("password", { required: "Enter your password." })}
        />
        {errors.password && <span className="field-error">{errors.password.message}</span>}
        <button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
