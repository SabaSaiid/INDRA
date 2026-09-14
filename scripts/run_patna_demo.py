#!/usr/bin/env python3
"""
INDRA Platform - Demonstration Runner
Scenario: Patna Urban Inundation (127 Reports -> 1 Verified Event)
Smart India Hackathon 2026 - Team Sixth Sense
"""

import json
import time
import sys
from pathlib import Path

def print_banner():
    banner = r"""
========================================================================
   ___ _   _ ____  ____      _     
  |_ _| \ | |  _ \|  _ \    / \    
   | ||  \| | | | | |_) |  / _ \   
   | || |\  | |_| |  _ <  / ___ \  
  |___|_| \_|____/|_| \_\/_/   \_\ 
  Intelligent National Disaster & Weather Platform
  Problem Statement: SIH26069 | Team: Sixth Sense
========================================================================
    """
    print(banner)

def run_simulation():
    print_banner()
    scenario_file = Path(__file__).resolve().parent.parent / "data" / "samples" / "patna_flood_scenario.json"
    
    if not scenario_file.exists():
        print(f"[ERROR] Sample dataset not found at {scenario_file}")
        sys.exit(1)
        
    with open(scenario_file, "r") as f:
        data = json.load(f)
        
    metadata = data["scenario_metadata"]
    breakdown = data["evidence_breakdown"]
    fused_output = data["verification_fusion_output"]
    
    print(f"[*] Scenario Loaded: {metadata['title']}")
    print(f"[*] Location: {metadata['location']}")
    print(f"[*] Total Raw Incoming Signals: {metadata['total_raw_signals']}\n")
    time.sleep(0.5)
    
    print("--- [STAGE 1: COLLECT] ---")
    print(f"  -> Ingesting {breakdown['citizen_reports']} Citizen App mobile submissions...")
    time.sleep(0.3)
    print(f"  -> Scraping {breakdown['social_media_posts']} Social Media #IMD and weather posts...")
    time.sleep(0.3)
    print(f"  -> Querying {breakdown['imd_automatic_weather_stations']} IMD Automatic Weather Stations...")
    time.sleep(0.3)
    print(f"  -> Pulling telemetry from {breakdown['cwc_river_level_sensors']} CWC River Gauges...")
    time.sleep(0.3)
    print(f"  -> Ingesting {breakdown['verified_multimedia_evidence']} crowdsourced photo/video payloads...")
    time.sleep(0.5)
    print(f"[✔] COLLECT Complete: 127 total signals queued in Redpanda streaming bus.\n")
    
    print("--- [STAGE 2: UNDERSTAND (AI & Geo Processing)] ---")
    print("  -> NLP Worker: Generating sentence embeddings (all-MiniLM-L6-v2)...")
    time.sleep(0.4)
    print("  -> Deduplication: 112 text descriptions grouped into 2 semantic intent clusters.")
    time.sleep(0.3)
    print("  -> Geospatial: Running PostGIS ST_ClusterDBSCAN (eps=5km, min_points=2)...")
    time.sleep(0.4)
    print(f"  -> Spatial Cohesion: 1 compact spatial cluster identified over Central Patna ({metadata['fused_event_summary']['impact_radius_km']} km radius).")
    time.sleep(0.3)
    print("  -> Computer Vision: EXIF validation passed; water level segmented (Waist Deep).")
    time.sleep(0.4)
    print("[✔] UNDERSTAND Complete: Structured event candidate generated.\n")
    
    print("--- [STAGE 3: VERIFY (Multi-Source Fusion Engine)] ---")
    factors = fused_output["verification_factors"]
    print(f"  -> Source Diversity: {factors['source_diversity_count']} distinct independent channels.")
    print(f"  -> Weather Station Agreement: {factors['station_agreement_score'] * 100:.0f}% correlation with Patna Airport IMD AWS (82.4mm rainfall).")
    print(f"  -> Spatial Cohesion Score: {factors['spatial_dbscan_cluster_cohesion'] * 100:.0f}%")
    print(f"  -> Multimedia Validation Score: {factors['cv_multimedia_validation_score'] * 100:.0f}%")
    time.sleep(0.5)
    
    confidence = fused_output["confidence_score"] * 100
    print(f"\n========================================================")
    print(f" [RESULT] FUSED VERIFIED EVENT: {fused_output['event_id']}")
    print(f" Title:       {fused_output['title']}")
    print(f" Severity:    {fused_output['severity']}")
    print(f" Confidence:  {confidence:.1f}%")
    print(f" Action:      {fused_output['threshold_action']} (Threshold >= 90%)")
    print(f" Alert Sent:  {', '.join(fused_output['alert_dispatched_to'])}")
    print(f"========================================================")
    print(f"\n[✔] Demonstration finished: 127 scattered signals condensed into 1 actionable alert!")

if __name__ == "__main__":
    run_simulation()
