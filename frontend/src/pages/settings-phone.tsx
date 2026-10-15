import { useState } from "react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { counted, upperFirst } from "@/lib/format";
import { REVEAL } from "@/lib/motion";
import {
  useApplications,
  useChooseApplication,
  useFixApplication,
  useMakeApplication,
  usePhoneAccount,
} from "@/lib/queries";
import type { AppSettings, PhoneAccount, PhoneApplication } from "@/lib/types";
import { PlivoAccountRow, ProviderPanel, SettingRow } from "@/pages/settings-keys";

const PROVIDERS = [{ value: "plivo", label: "Plivo" }];

/** The phone service that carries test calls: its credentials, the application that sends the
 * calls of the test numbers to this install, and how many test numbers it has. */
export function PhoneAccountPanel({ settings }: { settings: AppSettings }) {
  const account = usePhoneAccount();
  const credentials = Boolean(settings.secrets.plivo_auth_id && settings.secrets.plivo_auth_token);
  return (
    <ProviderPanel
      title="Phone account"
      description="The phone service that carries test calls."
      provider="plivo"
      canTest={credentials}
    >
      <SettingRow label="Provider" htmlFor="phone-provider">
        <div className="flex flex-wrap items-center gap-3">
          <Select items={PROVIDERS} value="plivo" disabled>
            <SelectTrigger id="phone-provider" className="min-w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {PROVIDERS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <span className="text-s-400 text-muted-foreground">More providers later</span>
        </div>
      </SettingRow>
      <PlivoAccountRow settings={settings} />
      {account.isError ? (
        <SettingRow label="Receiving application">
          <p className="text-s-400 text-destructive">{account.error.message}</p>
        </SettingRow>
      ) : account.data === undefined ? (
        <SettingRow label="Receiving application">
          <Skeleton className="h-9" />
        </SettingRow>
      ) : (
        <AccountRows account={account.data} />
      )}
    </ProviderPanel>
  );
}

function AccountRows({ account }: { account: PhoneAccount }) {
  const [changing, setChanging] = useState(false);
  const application = account.application;
  return (
    <>
      {!account.credentials_saved ? (
        <SettingRow label="Receiving application">
          <p className="text-s-400 text-muted-foreground">Save the Plivo credentials first.</p>
        </SettingRow>
      ) : application === null || changing ? (
        <ChooseApplication
          current={application?.id ?? null}
          onCancel={application ? () => setChanging(false) : undefined}
          onChosen={() => setChanging(false)}
        />
      ) : (
        <ReceivingApplication application={application} onChange={() => setChanging(true)} />
      )}
      <SettingRow label="Test numbers">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={
              account.test_numbers === 0 ? "text-s-400 text-muted-foreground" : "text-s-400"
            }
          >
            {account.test_numbers === 0
              ? "None yet"
              : counted(account.test_numbers, "number", "numbers")}
          </span>
          <span className="flex-1" />
          {application ? (
            <Button
              size="sm"
              variant="outline"
              nativeButton={false}
              render={<Link to="/numbers" />}
            >
              Open Numbers
            </Button>
          ) : (
            <Button size="sm" variant="outline" disabled>
              Open Numbers
            </Button>
          )}
        </div>
      </SettingRow>
    </>
  );
}

function ReceivingApplication({
  application,
  onChange,
}: {
  application: PhoneApplication;
  onChange: () => void;
}) {
  const fix = useFixApplication();
  const broken = application.problems.length > 0;
  // Only an application Plivo could read has URLs to fix.
  const fixable = broken && application.answer_url !== null;
  return (
    <SettingRow label="Receiving application">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span className="text-s-400">
            {application.name ?? "Unnamed application"}{" "}
            <span className="font-mono text-xs-400 text-muted-foreground">{application.id}</span>
          </span>
          {broken ? (
            <ul className="grid gap-0.5 text-s-400 text-warning-foreground">
              {application.problems.map((problem) => (
                <li key={problem} className="break-words">
                  {upperFirst(problem)}.
                </li>
              ))}
            </ul>
          ) : (
            application.answer_url && (
              <span className="text-s-400 break-all text-success-tag-foreground">
                Sends calls to {application.answer_url}
              </span>
            )
          )}
          {fix.isError && <p className="text-xs-400 text-destructive">{fix.error.message}</p>}
        </div>
        <div className="flex gap-2">
          {fixable && (
            <Button size="sm" disabled={fix.isPending} onClick={() => fix.mutate()}>
              {fix.isPending && <Spinner />}
              Fix URLs
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={onChange}>
            Change
          </Button>
        </div>
      </div>
    </SettingRow>
  );
}

/** Makes a new receiving application, or chooses one the account has. `onCancel` is set when an
 * application is chosen already, to keep it. */
function ChooseApplication({
  current,
  onCancel,
  onChosen,
}: {
  current: string | null;
  onCancel?: () => void;
  onChosen: () => void;
}) {
  const applications = useApplications();
  const make = useMakeApplication();
  const choose = useChooseApplication();
  const [picked, setPicked] = useState<string | null>(current);
  const items = (applications.data ?? []).map((application) => ({
    value: application.id,
    label: application.name ?? application.id,
  }));
  const busy = make.isPending || choose.isPending;
  return (
    <div className={`grid gap-3.5 border-t px-5 py-4 ${REVEAL}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="grid max-w-2xl gap-0.5">
          <span className="text-s-500">Receiving application</span>
          <span className="text-s-400 text-muted-foreground">
            A Plivo application sends the calls of your test numbers to Yaksh. Yaksh needs one
            before you can choose test numbers.
          </span>
        </div>
        {onCancel && (
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid content-start gap-2 rounded-lg border p-4">
          <span className="text-s-500">Make a new application</span>
          <span className="text-s-400 text-muted-foreground">
            Yaksh makes the application Yaksh in your Plivo account, with its calls sent to this
            install.
          </span>
          <span>
            <Button
              size="sm"
              disabled={busy}
              onClick={() => make.mutate(undefined, { onSuccess: onChosen })}
            >
              {make.isPending && <Spinner />}
              Make application
            </Button>
          </span>
          {make.isError && <p className="text-xs-400 text-destructive">{make.error.message}</p>}
        </div>
        <div className="grid content-start gap-2 rounded-lg border p-4">
          <label htmlFor="phone-application" className="text-s-500">
            Use an existing application
          </label>
          <span className="text-s-400 text-muted-foreground">
            Yaksh checks that it sends calls to this install, and offers to fix it.
          </span>
          <div className="flex flex-wrap gap-2">
            <Select
              items={items}
              value={picked}
              onValueChange={(value) => setPicked(value)}
              disabled={applications.data === undefined || items.length === 0}
            >
              <SelectTrigger id="phone-application" size="sm" className="min-w-44">
                {applications.isPending ? (
                  <Spinner />
                ) : (
                  <SelectValue
                    placeholder={items.length === 0 ? "No applications" : "Choose an application"}
                  />
                )}
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {items.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button
              size="sm"
              variant="outline"
              disabled={busy || picked === null || picked === current}
              onClick={() => picked && choose.mutate(picked, { onSuccess: onChosen })}
            >
              {choose.isPending && <Spinner />}
              Use
            </Button>
          </div>
          {applications.isError && (
            <p className="text-xs-400 text-destructive">{applications.error.message}</p>
          )}
          {choose.isError && <p className="text-xs-400 text-destructive">{choose.error.message}</p>}
        </div>
      </div>
    </div>
  );
}
