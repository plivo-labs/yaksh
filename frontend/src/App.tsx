import { ArrowUpRight } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function App() {
  return (
    <main className="mx-auto flex min-h-svh max-w-3xl flex-col justify-center px-6 py-16">
      <h1 className="text-6xl font-extrabold tracking-tighter sm:text-8xl">
        Truman<span className="text-primary">.</span>
      </h1>
      <p className="mt-6 max-w-xl text-xl leading-relaxed text-muted-foreground">
        Simulate, evaluate and improve AI agents.
        <br />
        Open source, runs on your own infrastructure.
      </p>
      <Button
        className="mt-10 self-start"
        variant="outline"
        size="lg"
        nativeButton={false}
        render={<a href="https://github.com/plivo-labs/truman" />}
      >
        View on GitHub
        <ArrowUpRight />
      </Button>
    </main>
  );
}
