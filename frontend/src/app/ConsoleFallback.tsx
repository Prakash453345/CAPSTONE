/** Spinner shown while a lazily loaded console page downloads. */
export function ConsoleFallback() {
  return (
    <div className="flex h-full items-center justify-center" role="status" aria-label="Loading">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
    </div>
  );
}
