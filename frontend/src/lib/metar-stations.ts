/**
 * Indian METAR Airport Stations Directory
 * Sourced from data/geo/india_metar_stations.csv
 * Used for multi-factor physical weather verification consensus.
 */

export interface MetarStation {
  icao: string;
  name: string;
  stateCode: string;
  lat: number;
  lng: number;
  elevationM: number;
  iata?: string;
}

export const INDIAN_METAR_STATIONS: MetarStation[] = [
  { icao: 'VIDP', name: 'New Delhi / Indira Gandhi Intl', stateCode: 'DL', lat: 28.567, lng: 77.117, elevationM: 236, iata: 'DEL' },
  { icao: 'VEPT', name: 'Patna / Jay Prakash Narayan Intl', stateCode: 'BR', lat: 25.591, lng: 85.088, elevationM: 53, iata: 'PAT' },
  { icao: 'VABB', name: 'Mumbai / Chhatrapati Shivaji Intl', stateCode: 'MH', lat: 19.1, lng: 72.859, elevationM: 14, iata: 'BOM' },
  { icao: 'VECC', name: 'Kolkata / Netaji Subhash Chandra Bose Intl', stateCode: 'WB', lat: 22.655, lng: 88.447, elevationM: 5, iata: 'CCU' },
  { icao: 'VOBL', name: 'Bengaluru / Kempegowda Intl', stateCode: 'KA', lat: 13.199, lng: 77.706, elevationM: 915, iata: 'BLR' },
  { icao: 'VOMM', name: 'Chennai / Anna Intl', stateCode: 'TN', lat: 12.994, lng: 80.181, elevationM: 16, iata: 'MAA' },
  { icao: 'VOHS', name: 'Hyderabad / Rajiv Gandhi Intl', stateCode: 'TS', lat: 17.24, lng: 78.43, elevationM: 617, iata: 'HYD' },
  { icao: 'VAAH', name: 'Ahmedabad / Sardar Vallabhbhai Patel Intl', stateCode: 'GJ', lat: 23.077, lng: 72.635, elevationM: 52, iata: 'AMD' },
  { icao: 'VEGT', name: 'Guwahati / Lokpriya Gopinath Bordoloi Intl', stateCode: 'AS', lat: 26.106, lng: 91.586, elevationM: 49, iata: 'GAU' },
  { icao: 'VEBI', name: 'Varanasi / Lal Bahadur Shastri Intl', stateCode: 'UP', lat: 25.452, lng: 82.859, elevationM: 81, iata: 'VNS' },
  { icao: 'VILK', name: 'Lucknow / Chaudhary Charan Singh Intl', stateCode: 'UP', lat: 26.761, lng: 80.884, elevationM: 123, iata: 'LKO' },
  { icao: 'VOCI', name: 'Kochi / Cochin Intl', stateCode: 'KL', lat: 10.152, lng: 76.402, elevationM: 9, iata: 'COK' },
  { icao: 'VOTV', name: 'Thiruvananthapuram Intl', stateCode: 'KL', lat: 8.482, lng: 76.92, elevationM: 4, iata: 'TRV' },
  { icao: 'VEBS', name: 'Bhubaneswar / Biju Patnaik Intl', stateCode: 'OD', lat: 20.244, lng: 85.818, elevationM: 42, iata: 'BBI' },
  { icao: 'VISM', name: 'Shimla Arpt', stateCode: 'HP', lat: 31.082, lng: 77.068, elevationM: 1546, iata: 'SLV' },
  { icao: 'VIDN', name: 'Dehradun / Jolly Grant Arpt', stateCode: 'UT', lat: 30.19, lng: 78.18, elevationM: 558, iata: 'DED' },
  { icao: 'VIAR', name: 'Amritsar / Sri Guru Ram Dass Jee Intl', stateCode: 'PB', lat: 31.71, lng: 74.797, elevationM: 230, iata: 'ATQ' },
  { icao: 'VIJP', name: 'Jaipur Intl', stateCode: 'RJ', lat: 26.824, lng: 75.812, elevationM: 385, iata: 'JAI' },
  { icao: 'VABP', name: 'Bhopal / Raja Bhoj Arpt', stateCode: 'MP', lat: 23.288, lng: 77.337, elevationM: 520, iata: 'BHO' },
  { icao: 'VANP', name: 'Nagpur / Dr. Babasaheb Ambedkar Intl', stateCode: 'MH', lat: 21.092, lng: 79.048, elevationM: 315, iata: 'NAG' },
  { icao: 'VAPO', name: 'Pune Arpt', stateCode: 'MH', lat: 18.582, lng: 73.92, elevationM: 592, iata: 'PNQ' },
  { icao: 'VERC', name: 'Ranchi / Birsa Munda Arpt', stateCode: 'JH', lat: 23.314, lng: 85.322, elevationM: 655, iata: 'IXR' },
  { icao: 'VARP', name: 'Raipur / Swami Vivekananda Arpt', stateCode: 'CG', lat: 21.18, lng: 81.739, elevationM: 317, iata: 'RPR' },
  { icao: 'VOVI', name: 'Visakhapatnam Intl', stateCode: 'AP', lat: 17.721, lng: 83.224, elevationM: 5, iata: 'VTZ' },
  { icao: 'VOVZ', name: 'Vijayawada Arpt', stateCode: 'AP', lat: 16.53, lng: 80.797, elevationM: 25, iata: 'VGA' },
  { icao: 'VOML', name: 'Mangaluru Intl', stateCode: 'KA', lat: 12.961, lng: 74.89, elevationM: 102, iata: 'IXE' },
  { icao: 'VOCL', name: 'Kozhikode / Calicut Intl', stateCode: 'KL', lat: 11.137, lng: 75.955, elevationM: 104, iata: 'CCJ' },
  { icao: 'VOCB', name: 'Coimbatore Intl', stateCode: 'TN', lat: 11.029, lng: 77.043, elevationM: 402, iata: 'CJB' },
  { icao: 'VOMD', name: 'Madurai Arpt', stateCode: 'TN', lat: 9.835, lng: 78.093, elevationM: 139, iata: 'IXM' },
  { icao: 'VOTR', name: 'Tiruchirappalli Intl', stateCode: 'TN', lat: 10.765, lng: 78.71, elevationM: 88, iata: 'TRZ' },
  { icao: 'VAGD', name: 'Gondia Arpt', stateCode: 'MH', lat: 21.467, lng: 80.2, elevationM: 312, iata: 'GDB' },
  { icao: 'VEBD', name: 'Bagdogra Arpt', stateCode: 'WB', lat: 26.681, lng: 88.329, elevationM: 87, iata: 'IXB' },
  { icao: 'VEJT', name: 'Jorhat / Rowriah Arpt', stateCode: 'AS', lat: 26.732, lng: 94.175, elevationM: 95, iata: 'JRH' },
  { icao: 'VEMN', name: 'Dibrugarh / Mohanbari Arpt', stateCode: 'AS', lat: 27.484, lng: 95.018, elevationM: 110, iata: 'DIB' },
  { icao: 'VEIM', name: 'Imphal / Bir Tikendrajit Intl', stateCode: 'MN', lat: 24.76, lng: 93.897, elevationM: 774, iata: 'IMF' },
  { icao: 'VEAT', name: 'Agartala / Maharaja Bir Bikram Arpt', stateCode: 'TR', lat: 23.887, lng: 91.24, elevationM: 15, iata: 'IXA' },
  { icao: 'VISR', name: 'Srinagar Intl', stateCode: 'JK', lat: 33.987, lng: 74.774, elevationM: 1655, iata: 'SXR' },
  { icao: 'VIJU', name: 'Jammu / Satwari Arpt', stateCode: 'JK', lat: 32.689, lng: 74.837, elevationM: 314, iata: 'IXJ' },
  { icao: 'VILH', name: 'Leh / Kushok Bakula Rimpochee Arpt', stateCode: 'LA', lat: 34.136, lng: 77.547, elevationM: 3256, iata: 'IXL' },
];

/**
 * Calculates Haversine distance in kilometers between two geo coordinates.
 */
export function calculateHaversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371; // Earth radius in km
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return Math.round(R * c * 10) / 10;
}

/**
 * Finds the nearest civil aerodrome / METAR station for physical observation matching.
 */
export function findNearestMetarStation(
  lat: number,
  lng: number
): { station: MetarStation; distanceKm: number } {
  let nearest = INDIAN_METAR_STATIONS[0];
  let minDistance = calculateHaversineKm(lat, lng, nearest.lat, nearest.lng);

  for (let i = 1; i < INDIAN_METAR_STATIONS.length; i++) {
    const s = INDIAN_METAR_STATIONS[i];
    const d = calculateHaversineKm(lat, lng, s.lat, s.lng);
    if (d < minDistance) {
      minDistance = d;
      nearest = s;
    }
  }

  return { station: nearest, distanceKm: minDistance };
}
