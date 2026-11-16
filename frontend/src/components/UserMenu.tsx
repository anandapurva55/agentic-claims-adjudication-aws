import { useEffect, useRef, useState } from 'react'
import { initials } from '../authlib'
import type { Role } from '../types'

/** The signed-in person: initials in the header, and a menu with their name, role, what that role may approve, and sign out. */
export default function UserMenu({ name, role, onSignOut }: { name: string; role: Role; onSignOut: () => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <div className="um" ref={box}>
      <button className="um-av" onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open} aria-label={`Account menu for ${name}`}>{initials(name)}</button>
      {open && (
        <div className="um-menu" role="menu">
          <div className="um-who"><b>{name}</b><small>{role === 'senior' ? 'Senior adjuster' : 'Adjuster'}</small>
            <small>{role === 'senior' ? 'Can approve payouts above INR 200,000' : 'Payouts above INR 200,000 need a senior adjuster'}</small></div>
          <button role="menuitem" className="um-item" onClick={onSignOut}>Sign out</button>
        </div>
      )}
    </div>
  )
}
