import { isRouteErrorResponse, useRouteError } from "react-router";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export function RouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : "Something went wrong.";
  return (
    <Alert variant="destructive">
      <AlertTitle>This page could not be shown</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
