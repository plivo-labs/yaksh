import { ChevronLeft } from "lucide-react";
import { Link, useNavigate } from "react-router";

import { Button, buttonVariants } from "@/components/ui/button";

/** Goes back in the browser history. A page opened directly has no earlier page in the app,
 * so there it goes up to `fallback` and replaces the entry; a push would make the next Back
 * return here. `idx` is the history index that React Router keeps in `history.state`: 0 on the
 * first page, also after a replace. */
export function BackButton({ fallback }: { fallback: string }) {
  const navigate = useNavigate();
  const icon = <ChevronLeft className="size-6" />;
  if (window.history.state?.idx > 0) {
    return (
      <Button variant="ghost" size="icon-xs" aria-label="Back" onClick={() => navigate(-1)}>
        {icon}
      </Button>
    );
  }
  return (
    <Link
      to={fallback}
      replace
      aria-label="Back"
      className={buttonVariants({ variant: "ghost", size: "icon-xs" })}
    >
      {icon}
    </Link>
  );
}
