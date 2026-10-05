import { Pager } from "@/components/pager";
import { RunList } from "@/components/run-list";
import { usePageParam } from "@/hooks/use-page-param";
import { RUNS_PAGE, useRuns } from "@/lib/queries";

export function RunsPage() {
  const runs = useRuns(undefined, usePageParam());
  return (
    <div className="grid gap-6">
      <div className="flex min-h-[30px] items-center">
        <h1 className="text-h3-500">Runs</h1>
      </div>
      <div>
        <RunList
          query={runs}
          place="page"
          showAgent
          empty="No runs yet. Open an agent, select scenarios on its Scenarios tab and click Run."
        />
        <Pager className="mt-4" query={runs} pageSize={RUNS_PAGE} />
      </div>
    </div>
  );
}
