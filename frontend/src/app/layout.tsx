import type { Metadata } from 'next';
import './globals.css';
import { LanguageProvider } from '@/lib/i18n';
import dynamic from 'next/dynamic';

const IdleLockOverlay = dynamic(() => import('@/components/IdleLockOverlay'), { ssr: false });
const RoleProvider = dynamic(
  () => import('@/lib/useRoleContext').then((m) => ({ default: m.RoleProvider })),
  { ssr: false },
);

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
        {/* Noto Sans Indian scripts — Devanagari, Bengali, Telugu, Tamil,
            Gujarati, Kannada, Malayalam, Oriya, Gurmukhi (Punjabi) */}
        <link
          href="https://fonts.googleapis.com/css2?family=Noto+Sans+Bengali:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&family=Noto+Sans+Gujarati:wght@400;500;600;700&family=Noto+Sans+Gurmukhi:wght@400;500;600;700&family=Noto+Sans+Kannada:wght@400;500;600;700&family=Noto+Sans+Malayalam:wght@400;500;600;700&family=Noto+Sans+Oriya:wght@400;500;600;700&family=Noto+Sans+Tamil:wght@400;500;600;700&family=Noto+Sans+Telugu:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-paper text-ink antialiased">
        {/* LanguageProvider: zero-backend client-side i18n — wraps entire app */}
        <LanguageProvider>
          <RoleProvider>
            <IdleLockOverlay />
            {children}
          </RoleProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
