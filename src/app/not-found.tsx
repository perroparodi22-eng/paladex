import Link from "next/link";

/** Fallback for URLs outside the site layout (the (site) group has its own). */
export default function RootNotFound() {
  return (
    <main className="grid min-h-dvh place-items-center bg-ground px-6 text-center">
      <div>
        <p className="title text-8xl leading-none text-court">404</p>
        <h1 className="mt-4 title text-5xl ">Out of the court</h1>
        <Link href="/" className="btn btn-primary mt-8">
          Back to Paladex
        </Link>
      </div>
    </main>
  );
}
