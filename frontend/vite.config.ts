import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv } from "vite"
import { isPublicSupabaseKey, isSupabaseUrl } from "./src/lib/auth.ts"

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_")
  const key = env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim()
  const url = env.VITE_SUPABASE_URL?.trim()
  if (Boolean(url) !== Boolean(key)) {
    throw new Error("Set both VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY, or leave both empty for demo access.")
  }
  if (key && !isPublicSupabaseKey(key)) {
    throw new Error("VITE_SUPABASE_PUBLISHABLE_KEY must be a publishable or legacy anon key. Secret/service_role keys must never be bundled.")
  }
  if (url && !isSupabaseUrl(url)) {
    throw new Error("VITE_SUPABASE_URL must be an HTTPS project origin, or a local HTTP Supabase origin.")
  }
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(import.meta.dirname, "./src"),
      },
    },
  }
})
