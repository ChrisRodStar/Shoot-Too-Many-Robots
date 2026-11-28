import { connection } from 'next/server';
import { getSplash } from '../../../lib/splash';
import { CompareSlider } from '../../compare-slider';

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
        <p>Drag the divider to compare the original 640 × 480 splash with the generated 3840 × 2880 remaster.</p>
      </header>
      {original && master ? (
        <figure className="splash-compare">
          <div className="splash-compare-canvas">
            <CompareSlider before="/compare/splash/original" after="/compare/splash/master"
              beforeLabel="Original" afterLabel="Generated" />
          </div>
          <figcaption className="splash-compare-caption">
            <span>Original on the left · generated on the right</span>
            <span className="splash-downloads">
              <a className="secondary" href="/compare/splash/original" download={original.filename}>Save original BMP</a>
              <a className="secondary" href="/compare/splash/master" download={master.filename}>Save full-resolution PNG</a>
              {replacement && (
                <a className="secondary" href="/compare/splash/new" download={replacement.filename}>Save 3840 × 2880 BMP</a>
              )}
            </span>
          </figcaption>
        </figure>
      ) : (
        <div className="splash-fallback">
          <p className="splash-missing">
            {!original && !master ? 'Both splash images are missing.'
              : master ? 'The original splash is missing.' : 'The generated splash is missing.'}
          </p>
          {original && (
            <>
              <img className="splash-preview" src="/compare/splash/original" alt="Original startup splash" />
              <div className="splash-downloads">
                <a className="secondary" href="/compare/splash/original" download={original.filename}>Save original BMP</a>
              </div>
            </>
          )}
          {!original && master && (
            <>
              <img className="splash-preview" src="/compare/splash/master" alt="Generated startup splash" />
              <div className="splash-downloads">
                <a className="secondary" href="/compare/splash/master" download={master.filename}>Save full-resolution PNG</a>
              </div>
            </>
          )}
        </div>
      )}
    </main>
  );
}
