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
        {/* Low Pressure type stack: Fraunces · Public Sans · JetBrains Mono */}
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Public+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-paper text-ink antialiased">
        {children}
      </body>
    </html>
  );
}
