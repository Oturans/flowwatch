"use client";

import { useAuth } from "./AuthContext";

/**
 * Small header chip showing the logged-in user with a logout button.
 * Drop this into the dashboard layout once auth is wired up.
 */
export function UserBadge() {
  const { user, tenant, logout } = useAuth();
  if (!user) return null;

  const initial = (user.email || "?").charAt(0).toUpperCase();
  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2 text-sm text-gray-600">
        <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-blue-100 text-blue-700 text-xs font-medium">
          {initial}
        </span>
        <div className="flex flex-col leading-tight">
          <span className="font-medium text-gray-900">{user.email}</span>
          {tenant && (
            <span className="text-xs text-gray-500">
              {tenant.name} · {user.role}
            </span>
          )}
        </div>
      </div>
      <button
        onClick={logout}
        className="text-sm text-gray-500 hover:text-gray-700 underline-offset-2 hover:underline"
      >
        Sign out
      </button>
    </div>
  );
}

export default UserBadge;
