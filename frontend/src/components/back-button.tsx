import { cn } from "cn";
import { ChevronLeft } from "lucide-react";
import { Link, useNavigate } from "react-router";

import { Button, buttonVariants } from "@/components/ui/button";

const className = "-ml-2 w-fit text-muted-foreground";

/** Goes back in the browser history. A page opened directly has no earlier page in the app,
 * so there it goes up to `fallback` and replaces the entry; a push would make the next Back
 * return here. `idx` is the history index that React Router keeps in `history.state`: 0 on the
 * first page, also after a replace. */
export function BackButton({ fallback }: { fallback: string }) {
  const navigate = useNavigate();
  const label = (
    <>
      <ChevronLeft data-icon="inline-start" />
      Back
    </>
  );
  if (window.history.state?.idx > 0) {
    return (
      <Button variant="ghost" size="sm" className={className} onClick={() => navigate(-1)}>
        {label}
      </Button>
    );
  }
  return (
    <Link
      to={fallback}
      replace
      className={cn(buttonVariants({ variant: "ghost", size: "sm", className }))}
    >
      {label}
    </Link>
  );
}
