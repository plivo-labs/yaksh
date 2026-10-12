import { useState } from "react";

import { DeleteDialog } from "@/components/confirm-dialogs";
import { Panel, PanelHeader } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { copyText } from "@/lib/clipboard";
import { APPEAR, REVEAL } from "@/lib/motion";
import { useNewSigningKey, useRemoveTriggerSecret, useSaveTriggerSecret } from "@/lib/queries";
import type { AppSettings } from "@/lib/types";
import { SettingRow } from "@/pages/settings-keys";

const SECRET_NAME = /^[A-Z][A-Z0-9_]{0,63}$/;

export function TriggersPanel({ settings }: { settings: AppSettings }) {
  return (
    <Panel>
      <PanelHeader title="Outbound triggers" />
      <SigningKeyRow
        saved={settings.secrets.trigger_signing_key?.hint ?? null}
        set={Boolean(settings.secrets.trigger_signing_key)}
      />
      <TriggerSecretsRow secrets={settings.trigger_secrets} />
    </Panel>
  );
}

function SigningKeyRow({ saved, set }: { saved: string | null; set: boolean }) {
  const generate = useNewSigningKey();
  const [shown, setShown] = useState<string | null>(null);
  return (
    <SettingRow
      label="Signing key"
      help="Lets the agent's system check that a trigger came from Yaksh."
    >
      {shown ? (
        <div className={`grid gap-2 ${APPEAR}`}>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              readOnly
              value={shown}
              aria-label="New signing key"
              className="min-w-0 flex-1 font-mono"
            />
            <Button
              size="sm"
              variant="outline"
              onClick={() => void copyText(shown, "Signing key copied")}
            >
              Copy
            </Button>
            <Button size="sm" onClick={() => setShown(null)}>
              Done
            </Button>
          </div>
          <span className="text-xs-400 text-warning-foreground">
            Copy it now. It won't be shown again.
          </span>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {set ? (
            <>
              <span className="font-mono text-s-400">••••••••{saved ?? ""}</span>
              <Badge variant="success">Saved</Badge>
            </>
          ) : (
            <Badge>Not set; triggers are not signed</Badge>
          )}
          <span className="flex-1" />
          <Button
            size="sm"
            variant="outline"
            disabled={generate.isPending}
            onClick={() => generate.mutate(undefined, { onSuccess: ({ key }) => setShown(key) })}
          >
            {generate.isPending && <Spinner />}
            {set ? "Generate new key" : "Generate key"}
          </Button>
        </div>
      )}
      {generate.isError && <p className="text-xs-400 text-destructive">{generate.error.message}</p>}
    </SettingRow>
  );
}

function TriggerSecretsRow({ secrets }: { secrets: AppSettings["trigger_secrets"] }) {
  const save = useSaveTriggerSecret();
  const remove = useRemoveTriggerSecret();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [removing, setRemoving] = useState<string | null>(null);
  const names = Object.keys(secrets);
  const nameValid = SECRET_NAME.test(name);
  return (
    <SettingRow
      label="Trigger secrets"
      help={
        <>
          Use a secret in a trigger template as{" "}
          <code className="font-mono">{"{{secrets.NAME}}"}</code>.
        </>
      }
    >
      {names.length > 0 && (
        <ul className="divide-y rounded-md border">
          {names.map((secret) => (
            <li key={secret} className="flex flex-wrap items-center gap-2 px-3 py-2">
              <span className="flex-1 font-mono text-s-400">{secret}</span>
              <span className="font-mono text-s-400 text-muted-foreground">
                ••••••••{secrets[secret].hint ?? ""}
              </span>
              <Button size="xs" variant="ghost" onClick={() => setRemoving(secret)}>
                Delete
              </Button>
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <form
          className={`grid gap-2 ${REVEAL}`}
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(
              { name, value },
              {
                onSuccess: () => {
                  setAdding(false);
                  setName("");
                  setValue("");
                },
              },
            );
          }}
        >
          <div className="flex flex-wrap gap-2">
            <Input
              aria-label="Secret name"
              placeholder="NAME"
              value={name}
              onChange={(event) => setName(event.target.value.toUpperCase())}
              aria-invalid={name !== "" && !nameValid}
              className="max-w-56 font-mono"
            />
            <Input
              aria-label="Secret value"
              type="password"
              autoComplete="off"
              placeholder="Value"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              className="min-w-0 flex-1"
            />
          </div>
          {name !== "" && !nameValid && (
            <p className="text-xs-400 text-destructive">
              Use capital letters, digits and _, starting with a letter.
            </p>
          )}
          {names.includes(name) && (
            <p className="text-xs-400 text-muted-foreground">This replaces the saved {name}.</p>
          )}
          {save.isError && <p className="text-xs-400 text-destructive">{save.error.message}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={!nameValid || !value || save.isPending}>
              {save.isPending && <Spinner />}
              Save
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div>
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            Add secret
          </Button>
        </div>
      )}
      <DeleteDialog
        name={removing ?? ""}
        description="Triggers that use it will fail."
        pending={remove.isPending}
        error={remove.isError ? remove.error.message : undefined}
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        onDelete={(close) => removing && remove.mutate(removing, { onSuccess: close })}
      />
    </SettingRow>
  );
}
