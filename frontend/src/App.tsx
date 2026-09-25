import { AuthProvider } from "./auth/AuthProvider"
import { AppRoot } from "./app/AppRoot"

function App() {
  return (
    <AuthProvider>
      <AppRoot />
    </AuthProvider>
  )
}

export default App
