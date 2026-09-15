# Client-Only Components

**CRITICAL RULE**: All browser-only, WebGL, DOM, or GIS libraries (`maplibre-gl`, `leaflet`, `react-leaflet`, `three`, `@react-three/*`, `globe.gl`, `react-globe.gl`, `cesium`, and their CSS assets) MUST ONLY be imported inside this directory.

Consumers anywhere else in the application MUST dynamically load components from this directory using `next/dynamic` with `{ ssr: false }`:

```tsx
import dynamic from 'next/dynamic';
import { MapCardSkeleton } from '@/components/ui/skeleton';

const GlobeEventMap = dynamic(() => import('@/components/client-only/GlobeEventMap'), {
  ssr: false,
  loading: () => <MapCardSkeleton />,
});
```

Direct static imports of browser-only libraries outside this directory are strictly forbidden and will fail the build via ESLint (`no-restricted-imports`).
