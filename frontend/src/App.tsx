import { useState, useEffect, useCallback } from 'react'
import { Login } from '@/components/login/Login'
import { Chat } from '@/components/chat/Chat'
import { API_BASE_URL, type CurrentUser } from '@/lib/config'

function App() {
  const [token, setToken] = useState<string | null>(null)
  const [user, setUser] = useState<CurrentUser | null>(null)

  // Load the signed-in user's real identity. The UI previously hardcoded "Admin User"
  // regardless of who logged in.
  useEffect(() => {
    // `user` is cleared by handleLogout rather than here: calling setState in an effect
    // body triggers a cascading render, and the effect only ever needs to *fetch*.
    if (!token) return
    const controller = new AbortController()
    fetch(`${API_BASE_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data && setUser(data))
      .catch(() => {
        /* aborted or offline — the avatar falls back to a placeholder */
      })
    return () => controller.abort()
  }, [token])

  // Silent token refresh: fires every 14 minutes to stay ahead of the 15-minute expiry.
  // On 200 → replace the token silently. On 401 → force re-login.
  useEffect(() => {
    if (!token) return

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
          method: 'POST',
          credentials: 'include', // sends the httpOnly refresh_token cookie
        })
        if (res.ok) {
          const data = await res.json()
          setToken(data.access_token)
        } else if (res.status === 401) {
          setToken(null)
        }
      } catch {
        // Network error — don't log the user out; try again on the next tick.
      }
    }, 14 * 60 * 1000)

    return () => clearInterval(interval)
  }, [token])

  const handleLogout = useCallback(() => {
    // Clear the refresh cookie server-side so the session cannot be resumed.
    fetch(`${API_BASE_URL}/api/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    }).catch(() => {
      /* best effort — the local token is dropped either way */
    })
    setToken(null)
    setUser(null)
  }, [])

  if (!token) {
    return <Login onLogin={(t) => setToken(t)} />
  }

  return <Chat token={token} user={user} onLogout={handleLogout} />
}

export default App
