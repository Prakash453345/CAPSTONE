import { cva } from "class-variance-authority";

/** Button style variants — kept separate so button.tsx only exports a component.
 *  Shapes follow Google's Material buttons: pills, flat fills, elevation on hover. */
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-[background-color,color,box-shadow] duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-primary-foreground hover:bg-primary/90 hover:shadow-elevation-1",
        default:
          "bg-surface text-primary border border-input hover:bg-primary-muted/60",
        subtle:
          "bg-transparent text-muted-foreground hover:bg-muted hover:text-foreground",
        outline:
          "border border-border bg-transparent hover:bg-muted hover:text-foreground",
        danger: "bg-status-critical text-white hover:bg-status-critical/90 dark:text-background",
        ghost: "hover:bg-muted hover:text-foreground",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4",
        lg: "h-10 px-5",
        icon: "h-9 w-9",
        "icon-sm": "h-8 w-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "md",
    },
  },
);
