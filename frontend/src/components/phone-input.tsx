import { Check, ChevronDown, Globe } from "lucide-react";
import { type ComponentProps, type KeyboardEvent, useRef, useState } from "react";
import PhoneNumberInput, {
  type Country,
  getCountryCallingCode,
  isSupportedCountry,
} from "react-phone-number-input";
import flags from "react-phone-number-input/flags";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

/** The country of the browser's language, for a number typed without its country code. */
function browserCountry(): Country {
  const region = new Intl.Locale(navigator.language).maximize().region;
  return region && isSupportedCountry(region) ? region : "US";
}

const DEFAULT_COUNTRY = browserCountry();

/** A phone number with its country's flag; the value is in E.164, like +14155550100, or empty.
 * A pasted number with its country code picks the country by itself. */
export function PhoneInput({
  value,
  onChange,
  className,
  ...props
}: Pick<
  ComponentProps<"input">,
  "id" | "required" | "className" | "aria-label" | "aria-invalid" | "aria-describedby"
> & {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <PhoneNumberInput
      {...props}
      international
      defaultCountry={DEFAULT_COUNTRY}
      value={value.startsWith("+") ? value : undefined}
      onChange={(next) => onChange(next ?? "")}
      countrySelectComponent={CountrySelect}
      inputComponent={Input}
      numberInputProps={{ className: "rounded-l-none" }}
      className={cn("flex", className)}
    />
  );
}

function Flag({ country }: { country?: Country }) {
  const Shape = country ? flags[country] : undefined;
  return (
    <span className="flex h-3.5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-xs [&_svg]:size-full">
      {Shape ? <Shape title="" /> : <Globe className="text-muted-foreground" />}
    </span>
  );
}

/** The country button and its searchable list, in the shape the phone input passes. */
function CountrySelect({
  value,
  onChange,
  options,
  disabled,
}: {
  value?: Country;
  onChange: (country?: Country) => void;
  options: { value?: Country; label: string }[];
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const needle = search.trim().toLowerCase();
  const shown = options.filter(
    (option): option is { value: Country; label: string } =>
      option.value !== undefined &&
      (option.label.toLowerCase().includes(needle) ||
        `+${getCountryCallingCode(option.value)}`.includes(needle)),
  );
  const current = options.find((option) => option.value === value)?.label ?? "No country";
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const pick = (country: Country) => {
    onChange(country);
    setOpen(false);
    setSearch("");
  };
  /** Up and down arrows move between the search box and the countries. */
  const move = (e: KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = [...(listRef.current?.querySelectorAll("button") ?? [])];
    if (items.length === 0) return;
    e.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "ArrowDown" ? Math.min(at + 1, items.length - 1) : at - 1;
    (next < 0 ? searchRef.current : items[next])?.focus();
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSearch("");
      }}
    >
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="outline"
            disabled={disabled}
            aria-label={`Country: ${current}`}
            className="h-9 gap-1 rounded-r-none border-r-0 px-2.5"
          />
        }
      >
        <Flag country={value} />
        <ChevronDown aria-hidden className="size-3.5 text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent
        align="start"
        aria-label="Choose a country"
        className="w-72 gap-0 p-0"
        onKeyDown={move}
      >
        <div className="border-b p-2">
          <Input
            ref={searchRef}
            autoFocus
            aria-label="Search countries"
            placeholder="Search countries"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && shown.length > 0) {
                e.preventDefault();
                pick(shown[0].value);
              }
            }}
          />
        </div>
        <ScrollArea className="h-64">
          {shown.length === 0 ? (
            <p className="px-3 py-4 text-s-400 text-muted-foreground">No country matches.</p>
          ) : (
            <ul ref={listRef} className="py-1">
              {shown.map((option) => (
                <li key={option.value}>
                  <button
                    type="button"
                    tabIndex={-1}
                    aria-pressed={option.value === value}
                    className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-s-400 outline-none hover:bg-hv1 focus-visible:bg-hv1"
                    onClick={() => pick(option.value)}
                  >
                    <Flag country={option.value} />
                    <span className="min-w-0 flex-1 truncate">{option.label}</span>
                    <span className="text-muted-foreground tabular-nums">
                      +{getCountryCallingCode(option.value)}
                    </span>
                    <Check
                      aria-hidden
                      className={cn("size-3.5", option.value === value ? "" : "invisible")}
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
