/**
 * AuthContext — global auth state, mirrors Angular's AuthService BehaviorSubject.
 *
 * Provides:
 *   currentUser   — { username, user_id, is_admin } | null
 *   login(u, p)   — calls POST /api/login, updates context + localStorage
 *   logout()      — calls POST /api/logout, clears context + localStorage
 */
import React, { createContext, useContext, useState, useCallback } from 'react';
import { apiLogin, apiLogout, getStoredUser, storeUser, clearUser } from '../api/auth';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [currentUser, setCurrentUser] = useState(getStoredUser);

  const login = useCallback(async (username, password) => {
    const uname = await apiLogin(username, password);
    // Store minimal user info locally (same shape as Angular's localStorage entry)
    const user = { username: uname };
    storeUser(user);
    setCurrentUser(user);
    return user;
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
