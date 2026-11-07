import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { ProjectsProvider } from './store/projects'
import { ToastProvider } from './components/Toast'
import { BackendProvider } from './backend'
import { AuthPage } from './pages/AuthPage'
import { Workspace } from './pages/Workspace'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <BackendProvider>
        <ToastProvider>
          <Routes>
            <Route path="/login" element={<AuthPage mode="login" />} />
            <Route path="/signup" element={<AuthPage mode="signup" />} />
            <Route
              path="/app"
              element={
                <RequireAuth>
                  <ProjectsProvider>
                    <Workspace />
                  </ProjectsProvider>
                </RequireAuth>
              }
            />
            <Route path="*" element={<Navigate to="/app" replace />} />
          </Routes>
        </ToastProvider>
        </BackendProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
