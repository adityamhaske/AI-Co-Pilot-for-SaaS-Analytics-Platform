import { useState, useEffect } from 'react'
import { Login } from '@/components/login/Login'
import { Chat } from '@/components/chat/Chat'

function App() {
  const [token, setToken] = useState<string | null>(null)
  const apiUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:6001"

  // Silent token refresh: fires every 14 minutes to stay ahead of the 15-minute expiry.
  // On 200 → replace token silently. On 401 → force re-login (refresh token expired/revoked).
  useEffect(() => {
    if (!token) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${apiUrl}/api/auth/refresh`, {
          method: 'POST',
          credentials: 'include', // sends the httpOnly refresh_token cookie
        });
        if (res.ok) {
          const data = await res.json();
          setToken(data.access_token);
        } else if (res.status === 401) {
          setToken(null);
        }
      } catch {
        // Network error — don't log the user out; try again on the next tick.
      }
    }, 14 * 60 * 1000);

    return () => clearInterval(interval);
  }, [token, apiUrl]);

  if (!token) {
    return <Login onLogin={(t) => setToken(t)} />
  }

  return <Chat token={token} onLogout={() => setToken(null)} />
}

export default App
