"use client";

import { usePathname } from "next/navigation";
import { ReactNode } from "react";
import { useAuth } from "./AuthContext";

/**
 * Wraps dashboard pages and renders a loading spinner while the
 * auth context is hydrating from localStorage. If the user ends up
 * unauthenticated, the auth context's redirect effect sends them to
 * /login automatically.
 *
 * Public paths (login, register) are rendered unconditionally.
 */
const PUBLIC_PATHS = new Set<string>(["/login", "/register"]);

export function AuthGuard({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const pathname = usePathname();
  const isPublic = pathname ? PUBLIC_PATHS.has(pathname) : false;

  if (isPublic) {
    return <>{children}</>;
  }

  if (status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-gray-500 text-sm">Checking session\u2026</div>
      </div>
    );
  }

  if (status === "unauthenticated") {
    // The effect in AuthContext will redirect; render nothing so we
    // don't flash protected content for a tick.
    return null;
  }

  return <>{children}</>;
}

export default AuthGuard;
