import { useApp } from './contexts/AppContext'
import Header from './components/Header'
import MessagePanel from './components/MessagePanel'
import AuthModal from './components/AuthModal'
import SettingsModal from './components/SettingsModal'

function App() {
  const { state } = useApp()
  const { connection, auth } = state
  const showAuthModal = !auth.isAuthenticated && connection.status !== 'disconnected'

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <MessagePanel />
      </div>
      {showAuthModal && <AuthModal />}
      <SettingsModal />
    </div>
  )
}

export default App
