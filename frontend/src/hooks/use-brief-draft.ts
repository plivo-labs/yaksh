import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { AgentDraft } from "@/hooks/use-agent-draft";
import { draftBrief, keys } from "@/lib/queries";

const noop = () => {};

/** Drafts the brief from the config. "Draft from config" asks on a click. `auto` names a draft an
 * import already asked for, from the config the form starts with: its answer fills the brief once,
 * if the brief is still empty, and success or failure then calls `onAutoDone` to forget it. An
 * answer for a config the person has changed since is dropped. */
export function useBriefDraft(
  form: AgentDraft,
  auto: string | null = null,
  onAutoDone: () => void = noop,
) {
  const { draft, set } = form;
  const [importedConfig] = useState(draft.config);
  const [autoError, setAutoError] = useState<string | null>(null);
  const currentConfig = useRef(draft.config);
  useEffect(() => {
    currentConfig.current = draft.config;
  }, [draft.config]);

  const onClick = useMutation({
    mutationFn: draftBrief,
    onMutate: () => setAutoError(null),
    onSuccess: (brief, config) => {
      if (config === currentConfig.current) set("brief", brief);
    },
  });
  const fromImport = useQuery({
    queryKey: keys.briefDraft(auto ?? ""),
    queryFn: () => draftBrief(importedConfig),
    enabled: auto !== null,
    staleTime: Infinity,
    retry: false,
    refetchOnMount: false,
    retryOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const settled = auto !== null && !fromImport.isFetching;
  const answer = settled ? fromImport.data : undefined;
  const failure = settled ? fromImport.error : null;
  useEffect(() => {
    if (answer === undefined && !failure) return;
    if (answer !== undefined && draft.brief.trim() === "" && draft.config === importedConfig) {
      set("brief", answer);
    }
    if (failure) setAutoError(failure.message);
    onAutoDone();
  }, [answer, failure, draft.brief, draft.config, importedConfig, set, onAutoDone]);

  return {
    drafting: onClick.isPending || (auto !== null && fromImport.isFetching),
    error: onClick.error?.message ?? autoError,
    canDraft: draft.config.trim() !== "",
    draft: () => onClick.mutate(draft.config),
  };
}

export type BriefDrafter = ReturnType<typeof useBriefDraft>;
