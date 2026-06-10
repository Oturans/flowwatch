"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "./AuthContext";

/**
 * /register page \u2014 creates a new tenant + first admin user.
 *
 * Slug is auto-derived from the org name (you can override) and must
 * be URL-safe (lowercase alphanumerics + hyphens).
 */
export function RegisterPage() {
  const router = useRouter();
  const { register } = useAuth();

  const [orgName, setOrgName] = useState("");
  const [slug, setSlug] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const slugify = (s: string) =>
    s
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 64);

  const onOrgChange = (v: string) => {
    setOrgName(v);
    if (!slug || slug === slugify(orgName)) {
      setSlug(slugify(v));
    }
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register({
        tenant: { name: orgName.trim(), slug: slug.trim() || slugify(orgName) },
        user: {
          email: email.trim(),
          password,
          full_name: fullName.trim() || null,
        },
      });
      router.replace("/");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Registration failed";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-md bg-white p-8 rounded-lg shadow-sm border border-gray-200"
      >
        <h1 className="text-2xl font-bold text-gray-900 mb-1">
          Create a FlowWatch account
        </h1>
        <p className="text-sm text-gray-500 mb-6">
          A new organization and admin user will be created.
        </p>

        <div className="grid grid-cols-1 gap-3">
          <Field
            label="Organization name"
            value={orgName}
            onChange={onOrgChange}
            placeholder="Acme Inc."
            required
          />
          <Field
            label="Organization slug"
            value={slug}
            onChange={setSlug}
            placeholder="acme-inc"
            pattern="[a-z0-9][a-z0-9-]*[a-z0-9]"
            required
            hint="URL-safe identifier; used as your tenant key."
          />
          <Field
            label="Your name"
            value={fullName}
            onChange={setFullName}
            placeholder="Ada Lovelace"
          />
          <Field
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            placeholder="you@company.com"
            autoComplete="email"
            required
          />
          <Field
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"
            autoComplete="new-password"
            minLength={8}
            required
            hint="Minimum 8 characters."
          />
        </div>

        {error && (
          <div
            role="alert"
            className="mt-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2"
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="mt-6 w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2 px-4 rounded text-sm transition"
        >
          {submitting ? "Creating account\u2026" : "Create account"}
        </button>

        <div className="mt-6 text-center text-sm text-gray-500">
          Already have an account?{" "}
          <Link href="/login" className="text-blue-600 hover:underline">
            Sign in
          </Link>
        </div>
      </form>
    </div>
  );
}

interface FieldProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
  autoComplete?: string;
  minLength?: number;
  pattern?: string;
  hint?: string;
}

function Field(p: FieldProps) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-gray-700 mb-1">
        {p.label}
      </span>
      <input
        type={p.type ?? "text"}
        value={p.value}
        onChange={(e) => p.onChange(e.target.value)}
        placeholder={p.placeholder}
        required={p.required}
        autoComplete={p.autoComplete}
        minLength={p.minLength}
        pattern={p.pattern}
        className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {p.hint && (
        <span className="block mt-1 text-xs text-gray-500">{p.hint}</span>
      )}
    </label>
  );
}

export default RegisterPage;
