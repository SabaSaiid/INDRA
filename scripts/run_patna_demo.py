#!/usr/bin/env python3
"""
INDRA Platform - SIH Demonstration Sequence (Slide 14 Narrative)
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
  "We are building an intelligence platform, not a weather app."
========================================================================
    """
    print(banner)

def run_demonstration():
    print_banner()
    scenario_file = Path(__file__).resolve().parent.parent / "data" / "samples" / "patna_flood_scenario.json"
    
    if not scenario_file.exists():
        print(f"[ERROR] Sample dataset not found at {scenario_file}")
        sys.exit(1)
        
    with open(scenario_file, "r") as f:
        data = json.load(f)
        
    meta = data["scenario_metadata"]
    fused = meta["fused_event_summary"]
    stats = fused["report_stats"]
    receipt = data["verification_receipt"]
    matrix = data["intelligence_matrix"]
    audit = data["audit_trail"]
    
    print("[SCENE 1: BASELINE]")
    print("  -> India Command Center map normal. Open-Meteo baseline live data active.")
    print("  -> System Status: HEALTHY | Active Incidents: 0 | Redpanda Broker: READY\n")
    time.sleep(0.6)
    
    print("[SCENE 3: THE SPIKE]")
    print(f"  -> High-volume event triggered: 127 simultaneous reports enter Patna via Kafka.")
    print(f"  -> Decoupled Kafka/Redpanda topic [indra.raw.reports] buffers traffic (50x spike).")
    print(f"  -> 0 reports dropped. Regulated AI worker processes stream in near-real-time.\n")
    time.sleep(0.6)
    
    print("[SCENE 5: AI & GEOSPATIAL FUSION]")
    print("  -> NLP Worker (BERT/Sentence-Transformers):")
    print("     - Input: 'Heavy rain flooded roads near Gandhi Maidan.'")
    print("     - Output: Event: Flood | Location: Gandhi Maidan | Severity: High")
    print("  -> Geospatial Worker (PostGIS + Uber H3 Hexagonal Indexing):")
    print("     - Coordinate Validation: GPS bounds normalized (-90/90 lat, -180/180 lon).")
    print("     - Geocoding: Administrative bound resolved -> India / Bihar / Patna.")
    print("     - ST_ClusterDBSCAN: Spatio-temporal clustering merges reports within 0.8km & 4 mins.")
    print(f"     - Result: {stats['total_incoming']} reports fused -> {stats['verified_corroborated']} verified, {stats['suspicious_flagged']} suspicious.\n")
    time.sleep(0.6)
    
    print("[SCENE 7: MULTI-MODAL EVIDENCE CORROBORATION]")
    print("  -> Computer Vision Pipeline (PyTorch/OpenCV):")
    print("     - Citizen Image (flood_123.jpg) -> Flood Probability: 0.91 | Quality: 0.86")
    print("  -> Anomaly Detection (Isolation Forest):")
    print("     - Current rainfall: 140mm vs seasonal baseline 35mm -> [RAINFALL ANOMALY DETECTED]\n")
    time.sleep(0.6)
    
    print("[SCENE 8: THE VERIFICATION RECEIPT & INTELLIGENCE MATRIX]")
    print("------------------------------------------------------------------------")
    print(f" THE VERIFICATION RECEIPT (Confidence: {receipt['confidence_total']} / 100)")
    print("------------------------------------------------------------------------")
    for item in receipt["breakdown"]:
        print(f"  [✓] {item['factor']:<28} ({item['weight_pct']}%) : Score {item['score']*100:.0f}% -> {item['weighted_points']:.1f} pts")
        print(f"      Evidence: {item['evidence']}")
    print("------------------------------------------------------------------------")
    print(f" Intelligence Matrix: [{matrix['quadrant']}]")
    print(f"                      Severity: {matrix['severity']} | Confidence: {matrix['confidence']}")
    print(f"                      Action:   {matrix['recommended_action']}")
    print("------------------------------------------------------------------------\n")
    time.sleep(0.6)
    
    print("[SCENE 10: ACTION & COMMAND CENTER DISPATCH]")
    print(f"  -> WebSocket Event Broadcast: [EventID: {fused['event_id']}] pushed to Next.js dashboard.")
    print("  -> Live map auto-updates with red inundation polygon (no manual refresh needed).")
    print(f"  -> Audit Trail Logged: \"{audit['log_entry']}\"")
    print(f"  -> SHA-256 Hash: {audit['tamper_proof_hash']}")
    print("\n========================================================================")
    print(" [✔] SIH DEMONSTRATION COMPLETE: 127 CHAOTIC SIGNALS -> 1 VERIFIED EVENT")
    print("========================================================================")

if __name__ == "__main__":
    run_demonstration()
