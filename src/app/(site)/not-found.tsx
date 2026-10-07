import Link from "next/link";
import { Container } from "@/components/layout/Section";
import { Icon } from "@/components/ui/Icon";

export default function NotFound() {
  return (
    <Container className="py-24">
      <div className="mx-auto max-w-xl text-center">
        <p className="num title text-8xl leading-none text-court">404</p>
        <h1 className="display mt-4 text-5xl">Out of the court</h1>
        <p className="mt-4 text-ink-2">That page or racket doesn&apos;t exist, or it has moved. Search the database or start from the showroom.</p>
        <div className="mt-8 flex flex-wrap justify-center gap-2">
          <Link href="/rackets" className="btn btn-primary">
            <Icon name="search" size={18} /> Browse rackets
          </Link>
          <Link href="/showroom" className="btn btn-secondary">
            3D showroom
          </Link>
        </div>
      </div>
    </Container>
  );
}
