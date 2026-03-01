import { useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Navbar from './components/Navbar'
import LoginPage from './pages/LoginPage'
import DocumentsPage from './pages/DocumentsPage'
import ChatPage from './pages/ChatPage'

export default function App() {
  const [user, setUser] = useState(null)   // { access_token, email, full_name, … }

  function handleLogin(data) {
    setUser(data)
  }

  function handleLogout() {
    setUser(null)
  }

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 transition-colors">
        {user && <Navbar user={user} onLogout={handleLogout} />}
        <Routes>
          <Route
            path="/login"
            element={user ? <Navigate to="/documents" replace /> : <LoginPage onLogin={handleLogin} />}
          />
          <Route
            path="/documents"
            element={user ? <DocumentsPage token={user.access_token} /> : <Navigate to="/login" replace />}
          />
          <Route
            path="/chat"
            element={user ? <ChatPage token={user.access_token} /> : <Navigate to="/login" replace />}
          />
          <Route path="*" element={<Navigate to={user ? '/documents' : '/login'} replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}
