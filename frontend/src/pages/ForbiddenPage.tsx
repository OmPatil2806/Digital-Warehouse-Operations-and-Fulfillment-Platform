import { ShieldAlert } from 'lucide-react'
import { Link } from 'react-router'

/** Shown when a logged-in user opens a page their role does not allow. */
export default function ForbiddenPage() {
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-amber-100 text-amber-600">
        <ShieldAlert size={28} aria-hidden="true" />
      </div>
      <p className="mt-4 text-sm font-semibold text-amber-600">403</p>
      <h1 className="mt-1 text-xl font-semibold">Access denied</h1>
      <p className="mt-2 text-sm text-slate-500">
        Your role does not allow you to view this page. Ask an administrator if you need access.
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
