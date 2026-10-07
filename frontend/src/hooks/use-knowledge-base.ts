import { useState } from "react";

import { useSaveKnowledgeBase } from "@/lib/queries";
import type {
  Agent,
  DocumentSummary,
  KnowledgeBaseDocument,
  KnowledgeBaseEntry,
} from "@/lib/types";

type Change = (current: KnowledgeBaseEntry[]) => KnowledgeBaseEntry[];

/** A knowledge base and where its changes go: saved on an agent at once, or held by a new
 * agent's form until the agent is added. */
export interface KnowledgeBaseSource {
  documents: KnowledgeBaseDocument[];
  saving: boolean;
  /** Applies `change` to the entries; `added` describes the documents it brings in. */
  change: (change: Change, added: DocumentSummary[]) => Promise<void>;
  /** Asked before a document is deleted; a draft deletes without asking. */
  deleteNote: string | null;
  /** What the panel is doing, such as reading an uploaded file; null when idle. */
  progress: string | null;
  setProgress: (progress: string | null) => void;
}

export function useSavedKnowledgeBase(agent: Agent): KnowledgeBaseSource {
  const save = useSaveKnowledgeBase(agent.id);
  const [progress, setProgress] = useState<string | null>(null);
  return {
    progress,
    setProgress,
    documents: agent.knowledge_base,
    saving: save.isPending,
    change: async (change) => {
      await save.mutateAsync(change);
    },
    deleteNote: "The agent stops using it. Earlier versions of the agent keep it.",
  };
}

function fromSummary(document: DocumentSummary): KnowledgeBaseDocument {
  return {
    document_id: document.id,
    name: document.name,
    media_type: document.media_type,
    size_bytes: document.size_bytes,
    characters: document.characters,
    pages: document.pages,
    empty_pages: document.empty_pages,
  };
}

/** The knowledge base of an agent that does not exist yet. The documents are uploaded now and
 * go with the request that adds the agent; `adding` locks the list while that request runs. */
export function useDraftKnowledgeBase(
  adding: boolean,
  initial: KnowledgeBaseDocument[] = [],
): KnowledgeBaseSource {
  const [documents, setDocuments] = useState(initial);
  const [progress, setProgress] = useState<string | null>(null);
  return {
    progress,
    setProgress,
    documents,
    saving: adding,
    deleteNote: null,
    change: async (change, added) =>
      setDocuments((current) => {
        const known = new Map(current.map((document) => [document.document_id, document]));
        for (const document of added) known.set(document.id, fromSummary(document));
        return change(current.map(({ document_id, name }) => ({ document_id, name }))).flatMap(
          (entry) => {
            const document = known.get(entry.document_id);
            return document ? [{ ...document, name: entry.name }] : [];
          },
        );
      }),
  };
}
