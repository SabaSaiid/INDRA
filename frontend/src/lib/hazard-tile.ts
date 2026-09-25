/**
 * INDRA Platform — hazard tile
 *
 * A colour and an icon per hazard, for the thumbnail beside an event in a
 * list. The tile illustrates the event type only: it is not imagery of the
 * event and says nothing about the place.
 *
 * Removed 25 Sep: the AI-generated hazard photos these tiles replace.
 */

export type HazardIconName =
  | 'flood'
  | 'rain'
  | 'thunderstorm'
  | 'cyclone'
  | 'fog'
  | 'heatwave'
  | 'landslide'
  | 'other';

export interface HazardTile {
  gradient: string;
  iconName: HazardIconName;
}

const HAZARD_TILES: Record<HazardIconName, HazardTile> = {
  flood: { gradient: 'linear-gradient(135deg, #1E3A8A, #0F172A)', iconName: 'flood' },
  rain: { gradient: 'linear-gradient(135deg, #1E40AF, #1E293B)', iconName: 'rain' },
  thunderstorm: { gradient: 'linear-gradient(135deg, #4C1D95, #1E1B4B)', iconName: 'thunderstorm' },
  cyclone: { gradient: 'linear-gradient(135deg, #0F766E, #134E4A)', iconName: 'cyclone' },
  fog: { gradient: 'linear-gradient(135deg, #475569, #1E293B)', iconName: 'fog' },
  heatwave: { gradient: 'linear-gradient(135deg, #B45309, #78350F)', iconName: 'heatwave' },
  landslide: { gradient: 'linear-gradient(135deg, #78350F, #3F2305)', iconName: 'landslide' },
  // A type none of the rules below recognise, or no type at all.
  other: { gradient: 'linear-gradient(135deg, #64748B, #334155)', iconName: 'other' },
};

export function getHazardTile(eventType?: string): HazardTile {
  if (!eventType) return HAZARD_TILES.other;

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
    return HAZARD_TILES.cyclone;
  }

  // 2. Thunderstorm, Lightning & Hail
  if (
    text.includes('thunder') ||
    text.includes('lightning') ||
    text.includes('hail') ||
    text.includes('storm')
  ) {
    return HAZARD_TILES.thunderstorm;
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
    return HAZARD_TILES.flood;
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
    return HAZARD_TILES.landslide;
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
    return HAZARD_TILES.fog;
  }

  // 6. Heatwave & Scorching Temperatures
  if (
    text.includes('heat') ||
    text.includes('warm') ||
    text.includes('temperature') ||
    text.includes('drought') ||
    text.includes('fire')
  ) {
    return HAZARD_TILES.heatwave;
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
    return HAZARD_TILES.rain;
  }

  return HAZARD_TILES.other;
}
