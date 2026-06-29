/**
 * App.jsx — top-level router, mirrors oldweb/app/app-routing.module.ts
 *
 * Only the login route is fully implemented so far.
 * All other routes render a <Placeholder> until they are ported.
 *
 * The route table matches the Angular routes exactly so URLs stay compatible.
 */
import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import RequireAuth from './router/RequireAuth';
import LoginPage from './components/login/LoginPage';
import BuildListPage from './components/build/BuildListPage';
import MirrorListPage from './components/mirror/MirrorListPage';
import MirrorDetailPage from './components/mirror/MirrorDetailPage';
import AboutPage from './components/about/AboutPage';
import UserListPage from './components/user/UserListPage';
import UserInfoPage from './components/user/UserInfoPage';
import BuildInfoPage from './components/build/BuildInfoPage';
import ProjectListPage from './components/project/ProjectListPage';
import ProjectDetailPage from './components/project/ProjectDetailPage';
import ProjectVersionDetailPage from './components/projectversion/ProjectVersionDetailPage';
import RepoListPage from './components/repo/RepoListPage';
import RepoDetailPage from './components/repo/RepoDetailPage';
import Layout from './components/layout/Layout';
import TokenListPage from './components/account/TokenListPage';
import AdminPage from './components/admin/AdminPage';
import MaintenancePage from './components/maintenance/MaintenancePage';

// Temporary placeholder for routes not yet ported
function Placeholder({ name }) {
  return (
    <div className="p-4">
      <h2>{name}</h2>
      <p className="text-muted">This page is being ported from the Angular UI.</p>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/maintenance" element={<MaintenancePage />} />

          {/* Protected — Layout wraps all authenticated pages */}
          <Route element={<RequireAuth><Layout /></RequireAuth>}>
            <Route path="/builds"                    element={<BuildListPage />} />
            <Route path="/build/:id"                 element={<BuildInfoPage />} />
            <Route path="/projects"                  element={<ProjectListPage />} />
            <Route path="/project/:name/versions"    element={<ProjectDetailPage />} />
            <Route path="/project/:name/permissions" element={<ProjectDetailPage />} />
            <Route path="/project/:name/tokens"      element={<ProjectDetailPage />} />
            <Route path="/project/:name/:version/*"  element={<ProjectVersionDetailPage />} />
            <Route path="/project/:name/*"           element={<ProjectDetailPage />} />
            <Route path="/mirrors"                   element={<MirrorListPage />} />
            <Route path="/mirror/:name/:version/*"   element={<MirrorDetailPage />} />
            <Route path="/repos"                     element={<RepoListPage />} />
            <Route path="/repo/:id/*"                element={<RepoDetailPage />} />

            <Route path="/users"                     element={<UserListPage />} />
            <Route path="/users/:username"           element={<UserInfoPage />} />
            <Route path="/tokens"                    element={<TokenListPage />} />
            <Route path="/about"                     element={<AboutPage />} />
            <Route path="/admin"                     element={<AdminPage />} />
            <Route path="/retention"                 element={<AdminPage />} />
            <Route path="/maintenance_config"        element={<AdminPage />} />
          </Route>

          {/* Default redirect — same as Angular ** → /builds */}
          <Route path="*" element={<Navigate to="/builds" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
