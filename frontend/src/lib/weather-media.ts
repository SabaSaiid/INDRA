/**
 * INDRA Platform — Weather Media Resolver
 * Maps event types, cities, and hazards to realistic high-resolution weather condition photos.
 * 100% frontend-side with graceful CSS gradient fallback.
 */

export interface WeatherMedia {
  src: string;
  alt: string;
  condition: string;
  gradient: string;
  iconName: 'flood' | 'rain' | 'thunderstorm' | 'cyclone' | 'fog' | 'heatwave' | 'landslide';
}

const WEATHER_MEDIA_CONFIG: Record<string, WeatherMedia> = {
  flood: {
    src: '/images/weather/flood.jpg',
    alt: 'Urban Flood Inundation',
    condition: 'Flood',
    gradient: 'linear-gradient(135deg, #1E3A8A, #0F172A)',
    iconName: 'flood',
  },
  rain: {
    src: '/images/weather/rain.jpg',
    alt: 'Intense Monsoon Rainfall',
    condition: 'Rainfall',
    gradient: 'linear-gradient(135deg, #1E40AF, #1E293B)',
    iconName: 'rain',
  },
  thunderstorm: {
    src: '/images/weather/thunderstorm.jpg',
    alt: 'Severe Lightning Thunderstorm',
    condition: 'Thunderstorm',
    gradient: 'linear-gradient(135deg, #4C1D95, #1E1B4B)',
    iconName: 'thunderstorm',
  },
  cyclone: {
    src: '/images/weather/cyclone.jpg',
    alt: 'Tropical Cyclone & Strong Winds',
    condition: 'Cyclone / Gale',
    gradient: 'linear-gradient(135deg, #0F766E, #134E4A)',
    iconName: 'cyclone',
  },
  fog: {
    src: '/images/weather/fog.jpg',
    alt: 'Dense Fog & Low Visibility',
    condition: 'Dense Fog',
    gradient: 'linear-gradient(135deg, #475569, #1E293B)',
    iconName: 'fog',
  },
  heatwave: {
    src: '/images/weather/heatwave.jpg',
    alt: 'Severe Summer Heatwave',
    condition: 'Heatwave',
    gradient: 'linear-gradient(135deg, #B45309, #78350F)',
    iconName: 'heatwave',
  },
  landslide: {
    src: '/images/weather/landslide.jpg',
    alt: 'Monsoon Hillside Landslide',
    condition: 'Landslide',
    gradient: 'linear-gradient(135deg, #78350F, #3F2305)',
    iconName: 'landslide',
  },
};

export function getWeatherMedia(eventType?: string): WeatherMedia {
  if (!eventType) return WEATHER_MEDIA_CONFIG.rain;

  const text = eventType.toLowerCase().trim();

  // 1. Cyclone, Gale & High Winds (prioritized over coastal inundation)
  if (
    text.includes('cyclone') ||
    text.includes('wind') ||
    text.includes('gale') ||
    text.includes('squall') ||
    text.includes('depression') ||
    text.includes('dust') ||
    text.includes('tornado')
  ) {
    return WEATHER_MEDIA_CONFIG.cyclone;
  }

  // 2. Thunderstorm, Lightning & Hail
  if (
    text.includes('thunder') ||
    text.includes('lightning') ||
    text.includes('hail') ||
    text.includes('storm')
  ) {
    return WEATHER_MEDIA_CONFIG.thunderstorm;
  }

  // 3. Flood, Urban Flooding & River Breaches
  if (
    text.includes('flood') ||
    text.includes('inundation') ||
    text.includes('waterlogging') ||
    text.includes('submerged') ||
    text.includes('breach') ||
    text.includes('overflow')
  ) {
    return WEATHER_MEDIA_CONFIG.flood;
  }

  // 4. Landslide, Mudslide & Slope Instability
  if (
    text.includes('landslide') ||
    text.includes('mudslide') ||
    text.includes('slope') ||
    text.includes('debris') ||
    text.includes('rockfall') ||
    text.includes('avalanche')
  ) {
    return WEATHER_MEDIA_CONFIG.landslide;
  }

  // 5. Dense Fog, Smog & Low Visibility
  if (
    text.includes('fog') ||
    text.includes('smog') ||
    text.includes('mist') ||
    text.includes('haze') ||
    text.includes('visibility') ||
    text.includes('cold') ||
    text.includes('frost')
  ) {
    return WEATHER_MEDIA_CONFIG.fog;
  }

  // 6. Heatwave & Scorching Temperatures
  if (
    text.includes('heat') ||
    text.includes('warm') ||
    text.includes('temperature') ||
    text.includes('drought') ||
    text.includes('fire')
  ) {
    return WEATHER_MEDIA_CONFIG.heatwave;
  }

  // 7. Rain, Cloudburst, Monsoon & Precipitation
  if (
    text.includes('rain') ||
    text.includes('cloudburst') ||
    text.includes('monsoon') ||
    text.includes('downpour') ||
    text.includes('shower') ||
    text.includes('precipitation')
  ) {
    return WEATHER_MEDIA_CONFIG.rain;
  }

  return WEATHER_MEDIA_CONFIG.rain;
}
