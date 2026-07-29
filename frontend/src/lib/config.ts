/**
 * Single source of truth for the API base URL.
 *
 * This was previously resolved inline in three components, each with its own fallback,
 * so changing the default meant remembering all three.
 */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:6001";

export interface CurrentUser {
  id: string;
  email: string;
  role: string;
  tenant_id: string;
}

/** Initials for the avatar, derived from the signed-in user rather than hardcoded. */
export function initialsFor(user: CurrentUser | null): string {
  if (!user?.email) return "?";
  const [local] = user.email.split("@");
  const parts = local.split(/[._-]/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return local.slice(0, 2).toUpperCase();
}
