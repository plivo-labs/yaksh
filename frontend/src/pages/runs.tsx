import { RunList } from "@/components/run-list";

export function RunsPage() {
  return (
    <div className="grid gap-6">
      <h1 className="text-h3-500">Runs</h1>
      <RunList />
    </div>
  );
}
