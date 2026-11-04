import { Link } from 'react-router'

/** Shown for any URL that does not match a route. */
export default function NotFoundPage() {
  return (
    <main className="mx-auto mt-24 max-w-md px-6 text-center">
      <p className="text-5xl font-bold text-slate-300">404</p>
      <h1 className="mt-4 text-xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-slate-500">The page you are looking for does not exist.</p>
      <Link to="/" className="mt-6 inline-block text-sm font-medium text-blue-700 hover:underline">
        Back to dashboard
      </Link>
    </main>
  )
}
