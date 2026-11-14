/** Isotipo: un frente de fuego dentro de una retícula de mando. */
export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="10" stroke="var(--color-accent)" strokeWidth="1.5" />
      <path d="M12 0v4M12 20v4M0 12h4M20 12h4" stroke="var(--color-accent)" strokeWidth="1.5" />
      <path
        d="M12 6c.6 2.4 3.5 3.8 3.5 7a3.5 3.5 0 0 1-7 0c0-1.3.6-2.2 1.3-3 .2 1 .8 1.6 1.4 1.8-.3-2 .1-4 .8-5.8Z"
        fill="var(--color-fire)"
      />
    </svg>
  );
}
