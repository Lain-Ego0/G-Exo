import { CockpitCTA } from "./sections/CockpitCTA";
import { Features } from "./sections/Features";
import { Footer } from "./sections/Footer";
import { Hero } from "./sections/Hero";
import { Loop } from "./sections/Loop";
import { Nav } from "./sections/Nav";
import { Specs } from "./sections/Specs";
import { Stats } from "./sections/Stats";

export default function App() {
  return (
    <div className="site-shell">
      <Nav />
      <main>
        <Hero />
        <Stats />
        <Loop />
        <Features />
        <Specs />
        <CockpitCTA />
      </main>
      <Footer />
    </div>
  );
}
