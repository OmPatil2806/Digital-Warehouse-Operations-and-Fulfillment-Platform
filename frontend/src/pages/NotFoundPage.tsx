import { SearchX } from 'lucide-react'
import { Link } from 'react-router'

/** Shown for any URL that does not match a route. */
export default function NotFoundPage() {
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-slate-200 text-slate-500">
        <SearchX size={28} aria-hidden="true" />
      </div>
      <p className="mt-4 text-sm font-semibold text-slate-500">404</p>
      <h1 className="mt-1 text-xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-slate-500">
        The page you are looking for does not exist or has moved.
      </p>
      <Link
        to="/"
        className="mt-6 inline-block rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800"
      >
        Back to dashboard
      </Link>
    </div>
  )
}
