/**
 * RequireAuth — React equivalent of Angular's AuthGuard.
 *
 * Wraps any route that needs a logged-in user.
 * Redirects to /login?returnUrl=<current path> if the user is not authenticated,
 * mirroring the Angular AuthGuard behaviour exactly.
 *
 * Admin-only routes pass requireAdmin={true}; the guard then checks
 * currentUser.is_admin (populated from GET /api/userinfo after login).
 *
 * Usage in the router:
 *
 *   <Route path="/builds" element={
 *     <RequireAuth><BuildList /></RequireAuth>
 *   } />
 *
 *   <Route path="/admin" element={
 *     <RequireAuth requireAdmin><AdminPage /></RequireAuth>
 *   } />
 */
import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function RequireAuth({ children, requireAdmin = false }) {
  const { currentUser, authReady } = useAuth();
  const location = useLocation();

  // Wait for session verification before rendering anything.
  if (!authReady) return null;

  if (!currentUser) {
    // Not logged in → redirect to login, preserving the intended destination
    return (
      <Navigate
        to={`/login?returnUrl=${encodeURIComponent(location.pathname + location.search)}`}
        replace
      />
    );
  }

  if (requireAdmin && !currentUser.is_admin) {
    // Logged in but not admin → redirect to unauthorized (or home)
    return <Navigate to="/builds" replace />;
  }

  return children;
}
