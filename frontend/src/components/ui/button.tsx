import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/** The Plivo console's button: uppercase mono label text, 2px corners, no shadow, and a 2px focus
 * ring offset by 2px. The default and outline kinds turn brand blue on hover, with a light band
 * sweeping across. */
const brandHover = cn(
  "hover:border-brand hover:bg-brand hover:text-brand-foreground",
  "relative overflow-hidden after:pointer-events-none after:absolute after:inset-0 after:bg-glint after:bg-size-[250%_100%] after:opacity-0 after:content-['']",
  "hover:after:animate-glint hover:after:opacity-100 motion-reduce:hover:after:animate-none",
);

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-md border border-transparent bg-clip-padding whitespace-nowrap transition-[color,background-color,border-color,box-shadow,translate,opacity] outline-none select-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: cn("bg-primary text-primary-foreground", brandHover),
        outline: cn("border-border bg-background text-foreground", brandHover),
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/90",
        tertiary: "bg-st1 text-foreground hover:bg-st1/80",
        ghost: "text-foreground hover:bg-hv2 aria-expanded:bg-hv2",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90 focus-visible:ring-destructive",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default:
          "h-9 gap-1.5 px-4 text-label tracking-[0.05em] has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3",
        xs: "h-6 gap-1 px-2 text-xs-500 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-[30px] gap-1 px-3 text-label tracking-[0.05em] has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        lg: "h-10 gap-1.5 px-8 text-label tracking-[0.05em] has-data-[icon=inline-end]:pr-5 has-data-[icon=inline-start]:pl-5",
        icon: "size-9",
        "icon-xs": "size-6 [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-[30px]",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
