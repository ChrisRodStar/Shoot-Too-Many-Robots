import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { Anton, Barlow_Condensed, IBM_Plex_Mono, Special_Elite } from 'next/font/google';
import './globals.css';

const display = Anton({
  subsets: ['latin'],
  weight: '400',
  variable: '--font-display',
  display: 'swap',
});

const body = Barlow_Condensed({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-body',
  display: 'swap',
});

const note = Special_Elite({
  subsets: ['latin'],
  weight: '400',
  variable: '--font-note',
  display: 'swap',
});

const mono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '600'],
  variable: '--font-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Decompilation Progress · Shoot Many Robots',
  description:
    'Live byte-exact matching progress for the Shoot Many Robots decompilation: functions, bytes, banks, and naming coverage.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${note.variable} ${mono.variable}`}
    >
      <body>
        <svg className="svg-filters" aria-hidden="true" focusable="false">
          <defs>
            <filter id="roughen" x="-4%" y="-4%" width="108%" height="108%">
              <feTurbulence
                type="fractalNoise"
                baseFrequency="0.035 0.09"
                numOctaves="2"
                seed="9"
                result="noise"
              />
              <feDisplacementMap
                in="SourceGraphic"
                in2="noise"
                scale="1.5"
                xChannelSelector="R"
                yChannelSelector="G"
              />
            </filter>
          </defs>
        </svg>
        {children}
      </body>
    </html>
  );
}
