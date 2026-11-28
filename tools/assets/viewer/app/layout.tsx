import type { ReactNode } from 'react';
import './globals.css';

export const metadata = {
  title: 'Asset Viewer · Shoot Many Robots',
  description: 'Browse and inspect the local extracted asset catalog.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
