import { useState } from 'react'
import { Login } from '@/components/login/Login'
import { Chat } from '@/components/chat/Chat'

function App() {
  const [token, setToken] = useState<string | null>(null)

  if (!token) {
    return <Login onLogin={(t) => setToken(t)} />
  }

  return <Chat token={token} onLogout={() => setToken(null)} />
}

export default App
