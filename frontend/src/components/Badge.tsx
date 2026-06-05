import type { ReactNode } from 'react';

export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`badge sev-${severity}`}>{severity}</span>;
}

export function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="badge category" title={category}>
      {category.replace(/_/g, ' ')}
    </span>
  );
}

export function Pill({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}
