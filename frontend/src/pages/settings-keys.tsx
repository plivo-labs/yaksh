import { CheckCircle2, CircleAlert } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialogs";
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
 * real work, even while the form holds changes. `canTest` is off while no key is saved. The
 * result sits beside the button, and the reason of a failure under the header; `edits` is the
 * panel's form values, and a change to them clears the result, which no longer describes them. */
export function ProviderPanel({
  title,
  description,
  provider,
  canTest,
  edits,
  children,
}: {
  title: string;
  description?: ReactNode;
  provider: SettingsProvider;
  canTest: boolean;
  edits?: string;
  children: ReactNode;
}) {
  const test = useTestProvider();
  const { reset } = test;
  useEffect(() => reset(), [edits, provider, reset]);
  const result = test.data;
  const failure = test.isError ? test.error.message : result && !result.ok ? result.detail : null;
  return (
    <Panel>
      <PanelHeader
        title={title}
        action={
          <div className="flex items-center gap-3">
            {(result || test.isError) && (
              <span
                key={test.submittedAt}
                role="status"
                className={`flex items-center gap-1.5 text-s-500 ${APPEAR} ${
                  failure === null ? "text-success-tag-foreground" : "text-destructive"
                }`}
              >
                {failure === null ? (
                  <CheckCircle2 className="size-4" aria-hidden />
                ) : (
                  <CircleAlert className="size-4" aria-hidden />
                )}
                {failure === null ? "Passed" : "Failed"}
              </span>
            )}
            <Button
              variant="outline"
              size="sm"
              disabled={!canTest || test.isPending}
              onClick={() => test.mutate(provider)}
            >
              {test.isPending && <Spinner />}
              {test.isPending ? "Testing" : "Test"}
            </Button>
          </div>
        }
      />
      {failure !== null && (
        <p
          key={test.submittedAt}
          className={`border-b px-5 py-2.5 text-xs-400 text-destructive ${REVEAL}`}
        >
          {failure}
        </p>
      )}
      {description && <p className="px-5 py-3 text-s-400 text-muted-foreground">{description}</p>}
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
  url,
  removable = false,
  removeWarning,
  checked = false,
}: {
  name: SecretName;
  label: string;
  help?: ReactNode;
  state: SecretState | undefined;
  /** The address the form shows for a key that has one: the key is checked there and saved
   * with it, so it never goes to an address the person does not see. */
  url?: string;
  removable?: boolean;
  /** What stops working without the key; when set, removing it asks first. */
  removeWarning?: { title: string; description: ReactNode };
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
              { name, value: value.trim(), url },
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
          {removable && (
            <RemoveButton
              saved={Boolean(state)}
              warning={removeWarning}
              pending={remove.isPending}
              error={remove.error?.message}
              onRemove={(done) =>
                remove.mutate(name, {
                  onSuccess: () => {
                    setSaved(false);
                    done();
                  },
                })
              }
            />
          )}
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            {state ? "Replace" : "Add key"}
          </Button>
        </div>
      )}
    </SettingRow>
  );
}

/** Remove, shown only while something is saved. With `warning`, it asks first; the dialog
 * stays mounted, so it closes smoothly after the saved value is gone. */
export function RemoveButton({
  saved,
  warning,
  pending,
  error,
  onRemove,
}: {
  saved: boolean;
  warning?: { title: string; description: ReactNode };
  pending: boolean;
  error?: string;
  onRemove: (done: () => void) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <>
      {saved && (
        <Button
          size="sm"
          variant="ghost"
          disabled={pending}
          onClick={() => (warning ? setConfirming(true) : onRemove(() => {}))}
        >
          Remove
        </Button>
      )}
      {warning && (
        <ConfirmDialog
          title={warning.title}
          description={warning.description}
          action="Remove"
          destructive
          pending={pending}
          error={error}
          open={confirming}
          onOpenChange={setConfirming}
          onConfirm={onRemove}
        />
      )}
    </>
  );
}

/** Two secrets that change together, such as an Auth ID and Auth token: a check never pairs a
 * new half with the other half of the old pair. `shown` is the saved pair's hint, null while
 * it is not saved; `children` are controls beside the change button, such as Remove. */
export function CredentialPairRow({
  label,
  inputId,
  shown,
  change,
  add,
  pending,
  error,
  onSave,
  onReset,
  children,
}: {
  label: string;
  inputId: string;
  shown: string | null;
  change: string;
  add: string;
  pending: boolean;
  error?: string;
  onSave: (pair: { auth_id: string; auth_token: string }, done: () => void) => void;
  onReset: () => void;
  children?: ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const [authId, setAuthId] = useState("");
  const [token, setToken] = useState("");
  const close = () => {
    setEditing(false);
    setAuthId("");
    setToken("");
    onReset();
  };
  return (
    <SettingRow label={label} htmlFor={editing ? inputId : undefined}>
      {editing ? (
        <form
          className={`grid gap-2 ${REVEAL}`}
          onSubmit={(event) => {
            event.preventDefault();
            onSave({ auth_id: authId.trim(), auth_token: token.trim() }, close);
          }}
        >
          <Input
            id={inputId}
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
          {error && <p className="text-xs-400 text-destructive">{error}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" size="sm" disabled={!authId.trim() || !token.trim() || pending}>
              {pending && <Spinner />}
              Check and save
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={close}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {shown !== null ? (
            <>
              <span className="font-mono text-s-400">{shown}</span>
              <Badge variant="success">Saved</Badge>
            </>
          ) : (
            <Badge>Not set</Badge>
          )}
          <span className="flex-1" />
          {children}
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            {shown !== null ? change : add}
          </Button>
        </div>
      )}
    </SettingRow>
  );
}

/** The Plivo account: its Auth ID and Auth token change together. */
export function PlivoAccountRow({ settings }: { settings: AppSettings }) {
  const save = useSavePlivoAccount();
  const id = settings.secrets.plivo_auth_id;
  return (
    <CredentialPairRow
      label="Auth ID and Auth token"
      inputId="plivo-auth-id"
      shown={id && settings.secrets.plivo_auth_token ? `••••••••${id.hint ?? ""}` : null}
      change="Change account"
      add="Add account"
      pending={save.isPending}
      error={save.isError ? save.error.message : undefined}
      onSave={(pair, done) => save.mutate(pair, { onSuccess: done })}
      onReset={save.reset}
    />
  );
}

/** The warning a changed address shows while its provider has a saved key. */
export function KeyRemovedNote({ address = "URL" }: { address?: string }) {
  return (
    <span className="text-warning-foreground">
      Saving removes the key for the old {address}. Add a key for this {address}.
    </span>
  );
}
