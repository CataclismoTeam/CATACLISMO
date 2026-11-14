import { cva, type VariantProps } from 'class-variance-authority';
import type { ButtonHTMLAttributes } from 'react';
import { cn } from '../lib/cn.ts';

// Único botón de la aplicación. En pantallas táctiles crece hasta 44 px de alto.
const button = cva(
  'inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-md border font-medium whitespace-nowrap transition-colors duration-150 ease-ui disabled:cursor-not-allowed disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-50 pointer-coarse:min-h-11',
  {
    variants: {
      variant: {
        primary:
          'border-transparent bg-accent text-on-accent hover:bg-accent-hover active:bg-accent',
        secondary:
          'border-line-strong bg-raised text-ink hover:bg-hover active:bg-raised aria-pressed:border-accent aria-pressed:bg-hover',
        ghost:
          'border-transparent bg-transparent text-ink-muted hover:bg-hover hover:text-ink aria-pressed:bg-hover aria-pressed:text-ink',
      },
      size: {
        md: 'h-9 px-3.5 text-sm',
        lg: 'h-11 px-5 text-base',
        icon: 'size-9 pointer-coarse:size-11',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
);

type Props = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>;

export function Button({ className, variant, size, type = 'button', ...props }: Props) {
  return <button type={type} className={cn(button({ variant, size }), className)} {...props} />;
}
