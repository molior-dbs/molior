/**
 * AuthContext — global auth state, mirrors Angular's AuthService BehaviorSubject.
 *
 * Provides:
 *   currentUser   — { username, user_id, is_admin } | null
 *   login(u, p)   — calls POST /api/login, updates context + localStorage
 *   logout()      — calls POST /api/logout, clears context + localStorage
 */
import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { apiLogin, apiLogout, apiGetUserInfo, getStoredUser, storeUser, clearUser } from '../api/auth';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [currentUser, setCurrentUser] = useState(getStoredUser);
  // Always false on page load — resolved only after the session check completes.
  // RequireAuth renders nothing until it flips to true.
  const [authReady, setAuthReady] = useState(false);

  // On every page load, verify the session cookie with the server.
  // This is the ground truth — localStorage is only a render cache.
  useEffect(() => {
    apiGetUserInfo()
      .then(info => {
        storeUser(info);
        setCurrentUser(info);
      })
      .catch(() => {
        // No valid session — clear any stale local state.
        clearUser();
        setCurrentUser(null);
      })
      .finally(() => setAuthReady(true));
  }, []);

  const login = useCallback(async (username, password) => {
    await apiLogin(username, password);
    // Fetch full user info (including is_admin) right after login
    const info = await apiGetUserInfo();
    storeUser(info);
    setCurrentUser(info);
    return info;
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    clearUser();
    setCurrentUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ currentUser, authReady, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
