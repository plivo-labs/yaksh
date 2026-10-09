import { type Draft, EMPTY_DRAFT } from "@/lib/agent-draft";
import { sessionDraft } from "@/lib/storage";
import {
  type AgentRule,
  type AgentSource,
  type KnowledgeBaseDocument,
  LANGUAGE_NAMES,
} from "@/lib/types";

const DRAFT_KEY = "yaksha.new-agent-draft";

/** Where a new agent's draft came from: a file Yaksha read, a file it only kept as the config, or
 * an agent read from a provider. */
export interface ImportedFrom {
  source: string;
  kind: "file" | "config-only" | "plivo-cx" | "elevenlabs" | "vapi" | "retell";
}

export const IMPORT_SOURCES: Record<ImportedFrom["kind"], AgentSource> = {
  file: "file",
  "config-only": "file",
  "plivo-cx": "plivo_cx",
  elevenlabs: "elevenlabs",
  vapi: "vapi",
  retell: "retell",
};

const IMPORT_KINDS: ReadonlySet<string> = new Set(Object.keys(IMPORT_SOURCES));

/** What the new-agent wizard keeps in this tab, so a reload does not lose it. */
export interface StoredDraft {
  draft: Draft;
  rules: AgentRule[];
  documents: KnowledgeBaseDocument[];
  /** The rule in the open form, by the `rule` value in the address that opened it. */
  openRule: { param: string; rule: AgentRule } | null;
  importedFrom: ImportedFrom | null;
  /** The brief draft an import asked for, until its answer fills the brief. */
  briefDraftId: string | null;
}

/** The draft this tab kept. A draft kept by an older version of the page lacks newer fields, so
 * the defaults fill them. */
export function readStoredDraft(): StoredDraft | null {
  const raw = sessionDraft.getItem(DRAFT_KEY);
  if (!raw) return null;
  try {
    const stored = JSON.parse(raw) as Partial<StoredDraft>;
    const draft: Draft = {
      ...EMPTY_DRAFT,
      ...stored.draft,
      outbound: { ...EMPTY_DRAFT.outbound, ...stored.draft?.outbound },
    };
    // A language Yaksha no longer has would leave the field empty and fail on save.
    if (!(draft.language in LANGUAGE_NAMES)) draft.language = EMPTY_DRAFT.language;
    return {
      draft,
      rules: stored.rules ?? [],
      documents: stored.documents ?? [],
      openRule: stored.openRule ?? null,
      importedFrom:
        stored.importedFrom && IMPORT_KINDS.has(stored.importedFrom.kind)
          ? stored.importedFrom
          : null,
      briefDraftId: stored.briefDraftId ?? null,
    };
  } catch {
    return null;
  }
}

/** Keeps the draft; false when the browser blocks or fills the storage. */
export function writeStoredDraft(kept: StoredDraft): boolean {
  const text = JSON.stringify(kept);
  sessionDraft.setItem(DRAFT_KEY, text);
  return sessionDraft.getItem(DRAFT_KEY) === text;
}

export function clearStoredDraft() {
  sessionDraft.removeItem(DRAFT_KEY);
}

/** Starts the wizard from an imported file, in place of any draft this tab kept. */
export function startImportedDraft(
  fields: Partial<Draft>,
  importedFrom: ImportedFrom,
  briefDraftId: string,
): boolean {
  return writeStoredDraft({
    draft: { ...EMPTY_DRAFT, ...fields },
    rules: [],
    documents: [],
    openRule: null,
    importedFrom,
    briefDraftId,
  });
}
