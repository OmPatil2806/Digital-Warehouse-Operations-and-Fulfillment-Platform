import { BrainCircuit, Boxes, PackageCheck, ShieldCheck } from 'lucide-react'
import { Outlet } from 'react-router'

const HIGHLIGHTS = [
  { icon: Boxes, text: 'Bin-level inventory with full movement history' },
  { icon: PackageCheck, text: 'Order lifecycle from picking to delivery' },
  { icon: BrainCircuit, text: 'Forecasts and delay predictions with TensorFlow' },
  { icon: ShieldCheck, text: 'Role-based access for every team' },
]

/** Layout for public pages (login): brand panel + centred content. */
export default function AuthLayout() {
  return (
    <div className="flex min-h-screen">
      <section className="hidden w-1/2 flex-col justify-between bg-slate-900 p-12 text-white lg:flex">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600">
            <PackageCheck size={22} aria-hidden="true" />
          </div>
          <p className="text-lg font-semibold">Digital Warehouse</p>
        </div>

        <div>
          <h2 className="text-3xl leading-tight font-semibold">
            Operations &amp; Fulfillment Platform
          </h2>
          <p className="mt-3 max-w-md text-slate-400">
            One traceable system for products, stock, orders and shipments — with machine learning
            that helps you decide.
          </p>
          <ul className="mt-8 space-y-4">
            {HIGHLIGHTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-slate-300">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-800">
                  <Icon size={16} aria-hidden="true" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-slate-500">© 2026 Om Dipak Patil · MSc AI &amp; Data Science</p>
      </section>

      <section className="flex flex-1 items-center justify-center bg-slate-50 px-6 py-12">
        <div className="w-full max-w-sm">
          <Outlet />
        </div>
      </section>
    </div>
  )
}
