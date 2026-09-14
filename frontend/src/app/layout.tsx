import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'INDRA — National Weather Intelligence Platform',
  description:
    'Real-time weather intelligence and disaster monitoring platform for India. Verified insights, citizen reports, and multi-source event correlation.',
  keywords: [
    'weather',
    'disaster management',
    'India',
    'INDRA',
    'weather intelligence',
    'flood monitoring',
    'IMD',
    'NDRF',
  ],
  authors: [{ name: 'Team Sixth Sense' }],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
      </head>
      <body className="bg-surface text-text-primary antialiased">
        {children}
      </body>
    </html>
  );
}
