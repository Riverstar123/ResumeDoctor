import { useState, type ReactNode } from 'react';

/** Native disclosure keeps all fields reachable by keyboard and error links. */
export function ReviewDetails({
  summary,
  children,
  initiallyOpen = false,
}: {
  summary: ReactNode;
  children: ReactNode;
  initiallyOpen?: boolean;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <details
      className="review-details"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>{summary}</summary>
      <div className="review-fields">{children}</div>
    </details>
  );
}
