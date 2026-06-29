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

  // On mount, if we have a stored session, refresh full user info (including is_admin)
  // in case the page was refreshed or the stored object is incomplete.
  useEffect(() => {
    if (getStoredUser()) {
      apiGetUserInfo()
        .then(info => {
          storeUser(info);
          setCurrentUser(info);
        })
        .catch(() => {
          // Session expired — clear stale local state
          clearUser();
          setCurrentUser(null);
        });
    }
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
    <AuthContext.Provider value={{ currentUser, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
