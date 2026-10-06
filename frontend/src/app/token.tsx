import { type SubmitEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

export function TokenGate({
  onToken,
  title = "API token",
  description = "The value of YAKSHA_API_TOKEN on the server.",
}: {
  onToken: (token: string) => void;
  title?: string;
  description?: string;
}) {
  const [value, setValue] = useState("");
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    if (value.trim()) onToken(value.trim());
  };
  return (
    <main className="flex min-h-svh items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="token">Token</FieldLabel>
                <Input
                  id="token"
                  type="password"
                  autoComplete="off"
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                />
              </Field>
              <Button type="submit" disabled={!value.trim()}>
                Continue
              </Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
