import clsx from "clsx";

// Base shimmering glass placeholder block — composed variants below are what pages
// actually use while RTK Query is isLoading. Never show a blank screen.
export function Skeleton({ className }) {
  return (
    <div className={clsx("relative overflow-hidden rounded-lg bg-white/10", className)}>
      <span className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/15 to-transparent" />
    </div>
  );
}

export function SkeletonTableRows({ count = 6, columns = 5 }) {
  return (
    <div className="glass space-y-3 p-6">
      {Array.from({ length: count }).map((_, row) => (
        <div key={row} className="flex animate-fade-in-up gap-4" style={{ animationDelay: `${row * 60}ms` }}>
          {Array.from({ length: columns }).map((__, col) => (
            <Skeleton key={col} className={clsx("h-5 flex-1", col === 0 && "max-w-[160px]")} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonStatCards({ count = 4 }) {
  return (
    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="glass animate-fade-in-up space-y-3 p-6" style={{ animationDelay: `${i * 60}ms` }}>
          <Skeleton className="h-3 w-1/2" />
          <Skeleton className="h-7 w-3/4" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonForm({ fields = 5 }) {
  return (
    <div className="glass space-y-5 p-6">
      {Array.from({ length: fields }).map((_, i) => (
        <div key={i} className="animate-fade-in-up space-y-2" style={{ animationDelay: `${i * 60}ms` }}>
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-10 w-full" />
        </div>
      ))}
    </div>
  );
}

export default Skeleton;
