import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

const isGitHubPagesBuild = process.env.GITHUB_ACTIONS === "true"

export default defineConfig({
  base: isGitHubPagesBuild
    ? "/NOVA-AI-Personal-Assistant/"
    : "/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
  },
})
