/** The product mark and name. Sized once here so the sign-in screen and the header agree. */
export default function Logo({ size = 'md' }: { size?: 'md' | 'lg' }) {
  return (
    <span className={`wordmark wordmark-${size}`}>
      <span className="mark" aria-hidden><svg viewBox="0 0 32 32" width="60%" height="60%"><path d="M18 3L7 18h7l-2 11 12-16h-7z" fill="currentColor" /></svg></span>
      <b>Claims Adjudication Copilot</b>
    </span>
  )
}
