import { CheckCircle2, CircleAlert } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Panel, PanelHeader } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { APPEAR, REVEAL } from "@/lib/motion";
import {
  useRemoveSecret,
  useSavePlivoAccount,
  useSaveSecret,
  useTestProvider,
} from "@/lib/queries";
import type { AppSettings, SecretName, SecretState, SettingsProvider } from "@/lib/types";

/** A label with its help on the left and its control on the right, as every setting is laid
 * out. */
export function SettingRow({
  label,
  htmlFor,
  help,
  children,
}: {
  label: string;
  htmlFor?: string;
  help?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-wrap gap-x-8 gap-y-2 border-t px-5 py-4">
      <div className="grid max-w-72 flex-[1_1_14rem] content-start gap-1">
        {htmlFor ? (
          <label htmlFor={htmlFor} className="text-s-500">
            {label}
          </label>
        ) : (
          <span className="text-s-500">{label}</span>
        )}
        {help && <span className="text-xs-400 text-muted-foreground">{help}</span>}
      </div>
      <div className="grid min-w-0 flex-[2_1_20rem] content-start gap-2">{children}</div>
    </div>
  );
}

/** A provider's settings, with a Test button that uses the saved ones for a small piece of
 * real work. */
export function ProviderPanel({
  title,
  description,
  provider,
  canTest,
  children,
}: {
  title: string;
  description?: ReactNode;
  provider: SettingsProvider;
  canTest: boolean;
  children: ReactNode;
}) {
  const test = useTestProvider();
  const result = test.data;
  return (
    <Panel>
      <PanelHeader
        title={title}
        action={
          <Button
            variant="outline"
            size="sm"
            disabled={!canTest || test.isPending}
            onClick={() => test.mutate(provider)}
          >
            {test.isPending && <Spinner />}
            Test
          </Button>
        }
      />
      {description && <p className="px-5 py-3 text-s-400 text-muted-foreground">{description}</p>}
      {(result || test.isError) && (
        <p
          key={test.submittedAt}
          role="status"
          className={`mx-5 mb-3 flex items-start gap-2 rounded-md px-3 py-2 text-s-400 ${APPEAR} ${
            result?.ok
              ? "bg-success-tag text-success-tag-foreground"
              : "bg-danger text-danger-foreground"
          }`}
        >
          {result?.ok ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
          ) : (
            <CircleAlert className="mt-0.5 size-4 shrink-0" />
          )}
          {test.isError
            ? test.error.message
            : result?.ok
              ? `Works. ${result.detail}`
              : `Failed: ${result?.detail}`}
        </p>
      )}
      {children}
    </Panel>
  );
}

/** A saved key, shown only by its last characters. Replacing it sends the new key to its
 * provider first; a key the provider refuses is not saved. */
export function KeyRow({
  name,
  label,
  help,
  state,
  removable = false,
  checked = false,
}: {
  name: SecretName;
  label: string;
  help?: ReactNode;
  state: SecretState | undefined;
  removable?: boolean;
  /** Whether the key's provider checks it before it is saved. */
  checked?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(false);
  const save = useSaveSecret();
  const remove = useRemoveSecret();
  const id = `secret-${name}`;
  const close = () => {
    setEditing(false);
    setValue("");
    save.reset();
  };
  return (
    <SettingRow label={label} htmlFor={editing ? id : undefined} help={help}>
      {editing ? (
        <form
          className={`grid gap-2 ${REVEAL}`}
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(
              { name, value: value.trim() },
              {
                onSuccess: () => {
                  close();
                  setSaved(true);
                },
              },
            );
          }}
        >
          <Input
            id={id}
            type="password"
            autoComplete="off"
            placeholder="Paste the value"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            aria-invalid={save.isError}
          />
          {save.isError && <p className="text-xs-400 text-destructive">{save.error.message}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" size="sm" disabled={!value.trim() || save.isPending}>
              {save.isPending && <Spinner />}
              {checked ? "Check and save" : "Save"}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={close}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {state ? (
            <>
              <span className="font-mono text-s-400">••••••••{state.hint ?? ""}</span>
              <Badge variant="success">{saved ? "Works. Saved." : "Saved"}</Badge>
            </>
          ) : (
            <Badge>Not set</Badge>
          )}
          <span className="flex-1" />
          {state && removable && (
            <Button
              size="sm"
              variant="ghost"
              disabled={remove.isPending}
              onClick={() => remove.mutate(name, { onSuccess: () => setSaved(false) })}
            >
              Remove
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            {state ? "Replace" : "Add key"}
          </Button>
        </div>
      )}
    </SettingRow>
  );
}

/** The Plivo account: its Auth ID and Auth token change together, so a check never pairs the
 * new half with the old account's other half. */
export function PlivoAccountRow({ settings }: { settings: AppSettings }) {
  const [editing, setEditing] = useState(false);
  const [authId, setAuthId] = useState("");
  const [token, setToken] = useState("");
  const save = useSavePlivoAccount();
  const id = settings.secrets.plivo_auth_id;
  const saved = id && settings.secrets.plivo_auth_token;
  const close = () => {
    setEditing(false);
    setAuthId("");
    setToken("");
    save.reset();
  };
  return (
    <SettingRow label="Auth ID and Auth token" htmlFor={editing ? "plivo-auth-id" : undefined}>
      {editing ? (
        <form
          className={`grid gap-2 ${REVEAL}`}
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate({ auth_id: authId.trim(), auth_token: token.trim() }, { onSuccess: close });
          }}
        >
          <Input
            id="plivo-auth-id"
            autoComplete="off"
            placeholder="Auth ID"
            value={authId}
            onChange={(event) => setAuthId(event.target.value)}
          />
          <Input
            type="password"
            autoComplete="off"
            aria-label="Auth token"
            placeholder="Auth token"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          {save.isError && <p className="text-xs-400 text-destructive">{save.error.message}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="submit"
              size="sm"
              disabled={!authId.trim() || !token.trim() || save.isPending}
            >
              {save.isPending && <Spinner />}
              Check and save
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={close}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {saved ? (
            <>
              <span className="font-mono text-s-400">••••••••{id.hint ?? ""}</span>
              <Badge variant="success">Saved</Badge>
            </>
          ) : (
            <Badge>Not set</Badge>
          )}
          <span className="flex-1" />
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            {saved ? "Change account" : "Add account"}
          </Button>
        </div>
      )}
    </SettingRow>
  );
}
