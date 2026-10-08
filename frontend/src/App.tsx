import { Button } from "@/components/ui/button"

function App() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-4 bg-background p-6 text-foreground">
      <h1 className="text-2xl font-semibold tracking-tight">Bridge</h1>
      <p className="text-sm text-muted-foreground">
        Vite + React + Tailwind + shadcn/ui
      </p>
      <Button>Get started</Button>
    </main>
  )
}

export default App
