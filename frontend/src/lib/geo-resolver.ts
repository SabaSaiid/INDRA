/**
 * INDRA Platform — Dynamic Geospatial Resolver & Indian Administrative Gazetteer
 * 
 * Provides robust coordinate validation, automatic inverted coordinate detection,
 * offline high-accuracy geocoding for all Indian States/UTs, major cities, and
 * disaster-prone regions, and GeoJSON generation for GPU-accelerated WebGL map rendering.
 */

// Bounding box of Indian sovereign territory (including islands)
export const INDIA_GEO_BOUNDS = {
  minLat: 6.5,
  maxLat: 37.6,
  minLng: 68.0,
  maxLng: 97.5,
};

export interface GeoLocation {
  city: string;
  state: string;
  lat: number;
  lng: number;
  region?: 'North' | 'South' | 'East' | 'West' | 'Central' | 'Northeast' | 'Islands';
  disasterRisk?: string[];
}

/**
 * High-precision gazetteer of Indian state capitals, key commercial hubs,
 * and high-risk meteorological/disaster monitoring nodes.
 */
export const INDIAN_GAZETTEER: Record<string, GeoLocation> = {
  // Eastern India
  'patna': { city: 'Patna', state: 'Bihar', lat: 25.6093, lng: 85.1376, region: 'East', disasterRisk: ['Urban Flooding', 'River Breach'] },
  'gaya': { city: 'Gaya', state: 'Bihar', lat: 24.7914, lng: 85.0002, region: 'East', disasterRisk: ['Heatwave', 'Drought'] },
  'kolkata': { city: 'Kolkata', state: 'West Bengal', lat: 22.5726, lng: 88.3639, region: 'East', disasterRisk: ['Cyclone Inundation', 'Urban Flooding', 'Thunderstorm'] },
  'siliguri': { city: 'Siliguri', state: 'West Bengal', lat: 26.7271, lng: 88.3953, region: 'East', disasterRisk: ['Flash Flood', 'Landslide'] },
  'darjeeling': { city: 'Darjeeling', state: 'West Bengal', lat: 27.0410, lng: 88.2663, region: 'East', disasterRisk: ['Landslide', 'Cloudburst'] },
  'bhubaneswar': { city: 'Bhubaneswar', state: 'Odisha', lat: 20.2961, lng: 85.8245, region: 'East', disasterRisk: ['Cyclone Inundation', 'Heavy Rainfall'] },
  'puri': { city: 'Puri', state: 'Odisha', lat: 19.8135, lng: 85.8312, region: 'East', disasterRisk: ['Cyclone Inundation', 'High Surge'] },
  'cuttack': { city: 'Cuttack', state: 'Odisha', lat: 20.4625, lng: 85.8828, region: 'East', disasterRisk: ['River Breach', 'Flooding'] },
  'ranchi': { city: 'Ranchi', state: 'Jharkhand', lat: 23.3441, lng: 85.3096, region: 'East', disasterRisk: ['Lightning', 'Flash Flood'] },

  // Western India
  'mumbai': { city: 'Mumbai', state: 'Maharashtra', lat: 19.0760, lng: 72.8777, region: 'West', disasterRisk: ['Urban Flooding', 'Strong Winds', 'High Tide Surge'] },
  'pune': { city: 'Pune', state: 'Maharashtra', lat: 18.5204, lng: 73.8567, region: 'West', disasterRisk: ['Heavy Rainfall', 'Waterlogging'] },
  'nagpur': { city: 'Nagpur', state: 'Maharashtra', lat: 21.1458, lng: 79.0882, region: 'Central', disasterRisk: ['Heatwave', 'Thunderstorm'] },
  'nashik': { city: 'Nashik', state: 'Maharashtra', lat: 19.9975, lng: 73.7898, region: 'West', disasterRisk: ['River Flood', 'Heavy Rainfall'] },
  'ahmedabad': { city: 'Ahmedabad', state: 'Gujarat', lat: 23.0225, lng: 72.5714, region: 'West', disasterRisk: ['Urban Flooding', 'Heatwave'] },
  'surat': { city: 'Surat', state: 'Gujarat', lat: 21.1702, lng: 72.8311, region: 'West', disasterRisk: ['River Inundation', 'Cyclone Inundation'] },
  'vadodara': { city: 'Vadodara', state: 'Gujarat', lat: 22.3072, lng: 73.1812, region: 'West', disasterRisk: ['River Breach', 'Flooding'] },
  'panaji': { city: 'Panaji', state: 'Goa', lat: 15.4909, lng: 73.8278, region: 'West', disasterRisk: ['Coastal Surge', 'Heavy Monsoon'] },

  // Northern India
  'new delhi': { city: 'New Delhi', state: 'Delhi', lat: 28.6139, lng: 77.2090, region: 'North', disasterRisk: ['Dense Fog', 'Air Quality', 'Urban Waterlogging'] },
  'delhi': { city: 'New Delhi', state: 'Delhi', lat: 28.6139, lng: 77.2090, region: 'North', disasterRisk: ['Dense Fog', 'Air Quality'] },
  'lucknow': { city: 'Lucknow', state: 'Uttar Pradesh', lat: 26.8467, lng: 80.9462, region: 'North', disasterRisk: ['Gomti River Flood', 'Dense Fog'] },
  'varanasi': { city: 'Varanasi', state: 'Uttar Pradesh', lat: 25.3176, lng: 82.9739, region: 'North', disasterRisk: ['Ganges Flood', 'Dense Fog'] },
  'kanpur': { city: 'Kanpur', state: 'Uttar Pradesh', lat: 26.4499, lng: 80.3319, region: 'North', disasterRisk: ['River Flood', 'Severe Cold Wave'] },
  'agra': { city: 'Agra', state: 'Uttar Pradesh', lat: 27.1767, lng: 78.0081, region: 'North', disasterRisk: ['Dense Fog', 'Thunderstorm'] },
  'dehradun': { city: 'Dehradun', state: 'Uttarakhand', lat: 30.3165, lng: 78.0322, region: 'North', disasterRisk: ['Cloudburst', 'Flash Flood', 'Landslide'] },
  'rishikesh': { city: 'Rishikesh', state: 'Uttarakhand', lat: 30.0869, lng: 78.2676, region: 'North', disasterRisk: ['Flash Flood', 'River Breach'] },
  'shimla': { city: 'Shimla', state: 'Himachal Pradesh', lat: 31.1048, lng: 77.1734, region: 'North', disasterRisk: ['Cloudburst', 'Landslide', 'Heavy Snowfall'] },
  'manali': { city: 'Manali', state: 'Himachal Pradesh', lat: 32.2432, lng: 77.1892, region: 'North', disasterRisk: ['Flash Flood', 'Avalanche'] },
  'srinagar': { city: 'Srinagar', state: 'Jammu and Kashmir', lat: 34.0837, lng: 74.7973, region: 'North', disasterRisk: ['Jhelum River Flood', 'Snowstorm'] },
  'jammu': { city: 'Jammu', state: 'Jammu and Kashmir', lat: 32.7266, lng: 74.8570, region: 'North', disasterRisk: ['Flash Flood', 'Landslide'] },
  'chandigarh': { city: 'Chandigarh', state: 'Punjab', lat: 30.7333, lng: 76.7794, region: 'North', disasterRisk: ['Urban Waterlogging', 'Dense Fog'] },
  'amritsar': { city: 'Amritsar', state: 'Punjab', lat: 31.6340, lng: 74.8723, region: 'North', disasterRisk: ['Dense Fog', 'Cold Wave'] },
  'jaipur': { city: 'Jaipur', state: 'Rajasthan', lat: 26.9124, lng: 75.7873, region: 'North', disasterRisk: ['Dust Storm', 'Heatwave', 'Flash Flood'] },
  'jodhpur': { city: 'Jodhpur', state: 'Rajasthan', lat: 26.2389, lng: 73.0243, region: 'North', disasterRisk: ['Severe Dust Storm', 'Heatwave'] },
  'barmer': { city: 'Barmer', state: 'Rajasthan', lat: 25.7521, lng: 71.3967, region: 'North', disasterRisk: ['Desert Dust Storm', 'Flash Inundation'] },

  // Southern India
  'chennai': { city: 'Chennai', state: 'Tamil Nadu', lat: 13.0827, lng: 80.2707, region: 'South', disasterRisk: ['Heavy Rainfall', 'Cyclone Inundation', 'Urban Flooding'] },
  'coimbatore': { city: 'Coimbatore', state: 'Tamil Nadu', lat: 11.0168, lng: 76.9558, region: 'South', disasterRisk: ['Heavy Rainfall', 'Windstorm'] },
  'madurai': { city: 'Madurai', state: 'Tamil Nadu', lat: 9.9252, lng: 78.1198, region: 'South', disasterRisk: ['Flash Flood', 'Heatwave'] },
  'bengaluru': { city: 'Bengaluru', state: 'Karnataka', lat: 12.9716, lng: 77.5946, region: 'South', disasterRisk: ['Severe Rainfall', 'Urban Flooding'] },
  'bangalore': { city: 'Bengaluru', state: 'Karnataka', lat: 12.9716, lng: 77.5946, region: 'South', disasterRisk: ['Severe Rainfall', 'Urban Flooding'] },
  'mangalore': { city: 'Mangalore', state: 'Karnataka', lat: 12.9141, lng: 74.8560, region: 'South', disasterRisk: ['Coastal Surge', 'Monsoon Flood'] },
  'hyderabad': { city: 'Hyderabad', state: 'Telangana', lat: 17.3850, lng: 78.4867, region: 'South', disasterRisk: ['Urban Inundation', 'Severe Thunderstorm'] },
  'visakhapatnam': { city: 'Visakhapatnam', state: 'Andhra Pradesh', lat: 17.6868, lng: 83.2185, region: 'South', disasterRisk: ['Cyclone Inundation', 'High Wind Surge'] },
  'vizag': { city: 'Visakhapatnam', state: 'Andhra Pradesh', lat: 17.6868, lng: 83.2185, region: 'South', disasterRisk: ['Cyclone Inundation', 'High Wind Surge'] },
  'vijayawada': { city: 'Vijayawada', state: 'Andhra Pradesh', lat: 16.5062, lng: 80.6480, region: 'South', disasterRisk: ['Krishna River Flood', 'Heatwave'] },
  'kochi': { city: 'Kochi', state: 'Kerala', lat: 9.9312, lng: 76.2673, region: 'South', disasterRisk: ['Coastal Erosion', 'Urban Flooding'] },
  'thiruvananthapuram': { city: 'Thiruvananthapuram', state: 'Kerala', lat: 8.5241, lng: 76.9366, region: 'South', disasterRisk: ['Heavy Rainfall', 'Sea Surge'] },
  'trivandrum': { city: 'Thiruvananthapuram', state: 'Kerala', lat: 8.5241, lng: 76.9366, region: 'South', disasterRisk: ['Heavy Rainfall', 'Sea Surge'] },
  'wayanad': { city: 'Wayanad', state: 'Kerala', lat: 11.6854, lng: 76.1320, region: 'South', disasterRisk: ['Massive Landslide', 'Flash Flood'] },
  'idukki': { city: 'Idukki', state: 'Kerala', lat: 9.8494, lng: 76.9804, region: 'South', disasterRisk: ['Dam Overflow', 'Landslide'] },

  // Northeastern India
  'guwahati': { city: 'Guwahati', state: 'Assam', lat: 26.1445, lng: 91.7362, region: 'Northeast', disasterRisk: ['Brahmaputra Flood', 'Heavy Rainfall'] },
  'silchar': { city: 'Silchar', state: 'Assam', lat: 24.8333, lng: 92.7789, region: 'Northeast', disasterRisk: ['Barak River Flood', 'Inundation'] },
  'shillong': { city: 'Shillong', state: 'Meghalaya', lat: 25.5788, lng: 91.8933, region: 'Northeast', disasterRisk: ['Heavy Cloudburst', 'Landslide'] },
  'imphal': { city: 'Imphal', state: 'Manipur', lat: 24.8170, lng: 93.9368, region: 'Northeast', disasterRisk: ['Flash Flood', 'Earthquake Zone'] },
  'agartala': { city: 'Agartala', state: 'Tripura', lat: 23.8315, lng: 91.2868, region: 'Northeast', disasterRisk: ['River Breach', 'Monsoon Flood'] },
  'aizawl': { city: 'Aizawl', state: 'Mizoram', lat: 23.7271, lng: 92.7176, region: 'Northeast', disasterRisk: ['Landslide', 'Heavy Rainfall'] },
  'kohima': { city: 'Kohima', state: 'Nagaland', lat: 25.6751, lng: 94.1086, region: 'Northeast', disasterRisk: ['Landslide', 'Flash Inundation'] },
  'gangtok': { city: 'Gangtok', state: 'Sikkim', lat: 27.3389, lng: 88.6065, region: 'Northeast', disasterRisk: ['GLOF', 'Flash Flood', 'Landslide'] },
  'itanagar': { city: 'Itanagar', state: 'Arunachal Pradesh', lat: 27.0844, lng: 93.6053, region: 'Northeast', disasterRisk: ['Cloudburst', 'River Flooding'] },

  // Central India
  'bhopal': { city: 'Bhopal', state: 'Madhya Pradesh', lat: 23.2599, lng: 77.4126, region: 'Central', disasterRisk: ['Urban Flooding', 'Heatwave'] },
  'indore': { city: 'Indore', state: 'Madhya Pradesh', lat: 22.7196, lng: 75.8577, region: 'Central', disasterRisk: ['Heavy Rainfall', 'Waterlogging'] },
  'jabalpur': { city: 'Jabalpur', state: 'Madhya Pradesh', lat: 23.1815, lng: 79.9864, region: 'Central', disasterRisk: ['Narmada Flood', 'Thunderstorm'] },
  'raipur': { city: 'Raipur', state: 'Chhattisgarh', lat: 21.2514, lng: 81.6296, region: 'Central', disasterRisk: ['Lightning', 'Heatwave'] },

  // Island Nodes
  'port blair': { city: 'Port Blair', state: 'Andaman and Nicobar', lat: 11.6234, lng: 92.7265, region: 'Islands', disasterRisk: ['Tsunami Threat', 'Cyclone Inundation'] },
  'kavaratti': { city: 'Kavaratti', state: 'Lakshadweep', lat: 10.5669, lng: 72.6420, region: 'Islands', disasterRisk: ['Sea Surge', 'Tropical Storm'] },
};

/**
 * Validates if coordinates fall within Indian sovereign territory.
 */
export function isCoordinateWithinIndia(lat: number, lng: number): boolean {
  return (
    typeof lat === 'number' &&
    typeof lng === 'number' &&
    !isNaN(lat) &&
    !isNaN(lng) &&
    lat >= INDIA_GEO_BOUNDS.minLat &&
    lat <= INDIA_GEO_BOUNDS.maxLat &&
    lng >= INDIA_GEO_BOUNDS.minLng &&
    lng <= INDIA_GEO_BOUNDS.maxLng
  );
}

/**
 * Detects if lat and lng were inverted (common PostGIS/Leaflet inversion bug).
 * E.g., lat: 72.87, lng: 19.07 instead of lat: 19.07, lng: 72.87.
 */
export function isInvertedCoordinate(lat: number, lng: number): boolean {
  return (
    lat >= INDIA_GEO_BOUNDS.minLng &&
    lat <= INDIA_GEO_BOUNDS.maxLng &&
    lng >= INDIA_GEO_BOUNDS.minLat &&
    lng <= INDIA_GEO_BOUNDS.maxLat
  );
}

/**
 * Sanitizes and guarantees exact, valid WGS-84 coordinates for any incoming incident.
 * 
 * Pipeline:
 * 1. Checks if coordinates are valid within India.
 * 2. If inverted (lat & lng swapped), automatically un-inverts them.
 * 3. If invalid, out-of-bounds, or missing, performs an intelligent Gazetteer lookup
 *    using city name, state, or free text matching.
 * 4. Applies a controlled micro-jitter if multiple incidents share the same city
 *    so pins stay faithful to the city without overlapping.
 */
export interface SanitizeIncidentOptions {
  lat?: number | null;
  lng?: number | null;
  city?: string;
  state?: string;
  text?: string;
  title?: string;
  eventType?: string;
  incidentIndex?: number;
}

export function sanitizeIncidentCoordinate(
  inputLatOrOpts: number | null | undefined | SanitizeIncidentOptions,
  inputLng?: number | null | undefined,
  cityHint?: string,
  stateHint?: string,
  textHint?: string,
  incidentIndex = 0
): { lat: number; lng: number; isResolved: boolean; city: string; state: string } {
  let lat: number;
  let lng: number;
  let city: string | undefined;
  let state: string | undefined;
  let text: string | undefined;
  let idx = 0;

  if (typeof inputLatOrOpts === 'object' && inputLatOrOpts !== null) {
    lat = Number(inputLatOrOpts.lat);
    lng = Number(inputLatOrOpts.lng);
    city = inputLatOrOpts.city;
    state = inputLatOrOpts.state;
    text = inputLatOrOpts.text || inputLatOrOpts.title || inputLatOrOpts.eventType;
    idx = inputLatOrOpts.incidentIndex || 0;
  } else {
    lat = Number(inputLatOrOpts);
    lng = Number(inputLng);
    city = cityHint;
    state = stateHint;
    text = textHint;
    idx = incidentIndex;
  }

  // Check for lat/lng inversion
  if (isInvertedCoordinate(lat, lng)) {
    const temp = lat;
    lat = lng;
    lng = temp;
  }

  // If already strictly valid within India
  if (isCoordinateWithinIndia(lat, lng)) {
    return {
      lat,
      lng,
      isResolved: false,
      city: city || 'India Node',
      state: state || '',
    };
  }

  // Fallback: Resolve via Gazetteer lookup
  const matched = resolveLocationFromText(city, state, text);
  if (matched) {
    // If multiple incidents occur in the exact same city, apply a tiny micro-jitter (max ~1km)
    const jitterAngle = (idx * 137.5 * Math.PI) / 180; // Golden ratio spiral
    const jitterDist = idx > 0 ? 0.008 : 0;
    const jitteredLat = Number((matched.lat + Math.sin(jitterAngle) * jitterDist).toFixed(4));
    const jitteredLng = Number((matched.lng + Math.cos(jitterAngle) * jitterDist).toFixed(4));

    return {
      lat: jitteredLat,
      lng: jitteredLng,
      isResolved: true,
      city: matched.city,
      state: matched.state,
    };
  }

  // Ultimate fallback to Central India command centroid
  return {
    lat: 22.0,
    lng: 82.0,
    isResolved: true,
    city: 'National Grid',
    state: 'India',
  };
}

/**
 * Searches the Indian Gazetteer for any city/district name found in the inputs.
 */
export function resolveLocationFromText(
  cityHint?: string,
  stateHint?: string,
  textHint?: string
): GeoLocation | null {
  const candidates = [cityHint, stateHint, textHint].filter(Boolean) as string[];
  const normalizedString = candidates.join(' ').toLowerCase();

  // Direct match
  for (const [key, loc] of Object.entries(INDIAN_GAZETTEER)) {
    const regex = new RegExp(`\\b${key}\\b`, 'i');
    if (regex.test(normalizedString) || normalizedString.includes(key)) {
      return loc;
    }
  }

  // State fallback
  const stateFallbacks: Record<string, string> = {
    'bihar': 'patna',
    'assam': 'guwahati',
    'maharashtra': 'mumbai',
    'delhi': 'new delhi',
    'tamil nadu': 'chennai',
    'west bengal': 'kolkata',
    'rajasthan': 'jaipur',
    'karnataka': 'bengaluru',
    'uttar pradesh': 'lucknow',
    'gujarat': 'ahmedabad',
    'odisha': 'bhubaneswar',
    'kerala': 'kochi',
    'telangana': 'hyderabad',
    'andhra pradesh': 'visakhapatnam',
    'madhya pradesh': 'bhopal',
    'uttarakhand': 'dehradun',
    'himachal pradesh': 'shimla',
    'punjab': 'chandigarh',
    'haryana': 'chandigarh',
    'jammu': 'srinagar',
    'kashmir': 'srinagar',
    'goa': 'panaji',
  };

  for (const [stateKey, cityKey] of Object.entries(stateFallbacks)) {
    if (normalizedString.includes(stateKey)) {
      return INDIAN_GAZETTEER[cityKey] || null;
    }
  }

  return null;
}

/**
 * Severity configuration for WebGL layers and HUD cards.
 */
export const SEVERITY_WEBGL_COLORS: Record<string, { core: string; halo: string; pulse: string }> = {
  critical: { core: '#EF4444', halo: 'rgba(239, 68, 68, 0.45)', pulse: 'rgba(239, 68, 68, 0.25)' },
  high: { core: '#F59E0B', halo: 'rgba(245, 158, 11, 0.40)', pulse: 'rgba(245, 158, 11, 0.20)' },
  moderate: { core: '#3B82F6', halo: 'rgba(59, 130, 246, 0.35)', pulse: 'rgba(59, 130, 246, 0.15)' },
  low: { core: '#64748B', halo: 'rgba(100, 116, 139, 0.30)', pulse: 'rgba(100, 116, 139, 0.10)' },
};

export const DISASTER_EMOJIS: Record<string, string> = {
  'Urban Flooding': '🌊',
  'Flood': '🌊',
  'Heavy Rainfall': '🌧️',
  'Severe Rainfall': '🌧️',
  'Rainfall': '🌧️',
  'Thunderstorm': '⚡',
  'Strong Winds': '💨',
  'Fog': '🌫️',
  'Cloudburst': '⛈️',
  'Landslide': '⛰️',
  'Cyclone': '🌀',
  'Cyclone Inundation': '🌀',
  'Default': '⚠️',
};
