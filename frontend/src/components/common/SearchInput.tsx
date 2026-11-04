import { Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

export const SEARCH_DEBOUNCE_MS = 300

interface SearchInputProps {
  /** Current search text (e.g. from the URL). */
  value: string
  /** Called after the user stops typing for a moment, or immediately when cleared. */
  onChange: (value: string) => void
  placeholder?: string
  label?: string
}

/**
 * Search box that waits until the user pauses typing before searching,
 * so the API is not called on every key stroke.
 */
export function SearchInput({
  value,
  onChange,
  placeholder = 'Search…',
  label = 'Search',
}: SearchInputProps) {
  const [text, setText] = useState(value)
  const [syncedValue, setSyncedValue] = useState(value)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Follow outside changes (e.g. browser back button) — adjust state during render.
  if (value !== syncedValue) {
    setSyncedValue(value)
    setText(value)
  }

  useEffect(() => () => clearTimeout(timer.current), [])

  const update = (next: string) => {
    setText(next)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => onChange(next.trim()), SEARCH_DEBOUNCE_MS)
  }

  const clear = () => {
    clearTimeout(timer.current)
    setText('')
    onChange('')
  }

  return (
    <div className="relative w-full max-w-xs">
      <Search
        size={16}
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-400"
      />
      <input
        type="search"
        aria-label={label}
        value={text}
        placeholder={placeholder}
        onChange={(event) => update(event.target.value)}
        className="w-full rounded-lg border border-slate-300 bg-white py-2 pr-8 pl-9 text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-600/20 [&::-webkit-search-cancel-button]:hidden"
      />
      {text && (
        <button
          type="button"
          onClick={clear}
          aria-label="Clear search"
          className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 text-slate-400 hover:text-slate-600"
        >
          <X size={14} aria-hidden="true" />
        </button>
      )}
    </div>
  )
}
