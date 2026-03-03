export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="text-4xl font-bold tracking-tight text-teal-400">
        Blueprint Dashboard
      </h1>
      <p className="mt-4 text-lg text-slate-400">
        Sovereign career architecture — pipeline active
      </p>
      <div className="mt-8 grid grid-cols-2 gap-4 text-sm">
        <div className="rounded-lg bg-slate-800 px-6 py-4">
          <p className="font-medium text-teal-400">Scout</p>
          <p className="text-slate-400">Awaiting configuration</p>
        </div>
        <div className="rounded-lg bg-slate-800 px-6 py-4">
          <p className="font-medium text-teal-400">Evaluator</p>
          <p className="text-slate-400">Awaiting configuration</p>
        </div>
        <div className="rounded-lg bg-slate-800 px-6 py-4">
          <p className="font-medium text-teal-400">Dashboard</p>
          <p className="text-slate-400">Online</p>
        </div>
        <div className="rounded-lg bg-slate-800 px-6 py-4">
          <p className="font-medium text-teal-400">Applier</p>
          <p className="text-slate-400">Awaiting configuration</p>
        </div>
      </div>
    </main>
  );
}
