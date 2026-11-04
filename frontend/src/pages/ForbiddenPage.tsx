import { Link } from 'react-router'

/** Shown when a logged-in user opens a page their role does not allow. */
export default function ForbiddenPage() {
  return (
    <main className="mx-auto mt-24 max-w-md px-6 text-center">
      <p className="text-5xl font-bold text-slate-300">403</p>
      <h1 className="mt-4 text-xl font-semibold">Access denied</h1>
      <p className="mt-2 text-sm text-slate-500">You do not have permission to view this page.</p>
      <Link to="/" className="mt-6 inline-block text-sm font-medium text-blue-700 hover:underline">
        Back to dashboard
      </Link>
    </main>
  )
}
