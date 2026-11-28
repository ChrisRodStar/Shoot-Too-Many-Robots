import { connection } from 'next/server';
import { getSplash } from '../../../lib/splash';

export const metadata = { title: 'Compare Startup Splash · Asset Viewer' };

export default async function SplashComparison() {
  await connection();
  const [original, master, replacement] = await Promise.all(
    ['original', 'master', 'new'].map(getSplash),
  );

  return (
    <main className="splash-comparison">
      <header className="splash-heading">
        <a href="/">← Asset Viewer</a>
        <h1>Startup splash</h1>
      </header>
      <div className="splash-versions">
        <figure>
          <figcaption>Original <span>640 × 480</span></figcaption>
          {original ? (
            <>
              <img src="/compare/splash/original" width="640" height="480" alt="Original startup splash" />
              <a className="secondary" href="/compare/splash/original" download={original.filename}>Save original BMP</a>
            </>
          ) : <p className="splash-missing">The original splash is missing.</p>}
        </figure>
        <figure>
          <figcaption>Generated splash <span>3840 × 2880</span></figcaption>
          {master ? (
            <>
              <img src="/compare/splash/master" width="3840" height="2880" alt="Generated startup splash" />
              <div className="splash-downloads">
                <a className="secondary" href="/compare/splash/master" download={master.filename}>Save full-resolution PNG</a>
                {replacement && (
                  <a className="secondary" href="/compare/splash/new" download={replacement.filename}>Save 3840 × 2880 BMP</a>
                )}
              </div>
            </>
          ) : <p className="splash-missing">The generated splash is missing.</p>}
        </figure>
      </div>
    </main>
  );
}
