# INDRA PostGIS Spatial Partitioning & High-Scale Indexing Strategy

**Document Reference:** INDRA-DATA-SPEC-07  
**Classification:** Database Architecture & High-Scale Ingestion  
**Status:** Approved for Implementation  

---

## 1. Context & Architectural Challenge

During peak monsoonal surges and cyclone landfalls, INDRA ingests up to 15,000 geospatial telemetry events per minute across citizen reports, automated IoT stream gauges, and IMD radar polygon alerts. Storing this high-velocity spatial time-series inside a single unpartitioned PostgreSQL table leads to:
1. Significant degradation of GiST spatial index updates due to random write page splits.
2. Inefficient table vacuums blocking read locks during emergency dashboard queries.
3. Slow chronological lookups for historical disaster comparisons.

This specification details INDRA's declarative partitioning architecture combining **Temporal Range Partitioning** with **Spatial Clustered Indexing**.

---

## 2. Declarative Table Partitioning Architecture

The root table `indra_incident_telemetry` is partitioned by `RANGE (reported_at)` using monthly sub-tables, with active months further sub-partitioned by regional administrative state code:

```sql
-- Root telemetry table
CREATE TABLE indra_incident_telemetry (
    id UUID NOT NULL,
    hazard_type VARCHAR(32) NOT NULL,
    severity_level VARCHAR(16) NOT NULL,
    reported_at TIMESTAMPTZ NOT NULL,
    state_code VARCHAR(4) NOT NULL,
    district_code VARCHAR(8) NOT NULL,
    h3_res8_index BIGINT NOT NULL,
    location GEOMETRY(Point, 4326) NOT NULL,
    sensor_attributes JSONB,
    verification_status VARCHAR(20) DEFAULT 'PENDING',
    PRIMARY KEY (id, reported_at, state_code)
) PARTITION BY RANGE (reported_at);

-- Monthly partition example: October 2026
CREATE TABLE telemetry_y2026_m10 PARTITION OF indra_incident_telemetry
    FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00')
    PARTITION BY LIST (state_code);

-- Regional sub-partition: Telangana & Andhra Pradesh
CREATE TABLE telemetry_y2026_m10_south_central PARTITION OF telemetry_y2026_m10
    FOR VALUES IN ('TG', 'AP');
```

---

## 3. Indexing Strategy & GiST Tuning

To balance high-throughput ingestion with instantaneous bounding box queries on the live `/analytics` dashboard:

1. **GiST Spatial Index on Active Sub-Tables:**
   ```sql
   CREATE INDEX idx_telemetry_202610_geom_gist 
   ON telemetry_y2026_m10_south_central USING GIST (location);
   ```
2. **BRIN Temporal Index on Historical Partitions:**
   For archived partitions ($> 90$ days old), expensive GiST indexes are dropped in favor of lightweight Block Range Indexes (BRIN) on `reported_at`, reducing disk storage footprint by up to 88%:
   ```sql
   CREATE INDEX idx_telemetry_historical_brin 
   ON telemetry_y2026_m07 USING BRIN (reported_at) WITH (pages_per_range = 128);
   ```
3. **H3 Discrete Index for Exact Cell Lookups:**
   ```sql
   CREATE INDEX idx_telemetry_h3_btree 
   ON telemetry_y2026_m10_south_central (h3_res8_index);
   ```

---

## 4. Automated Partition Maintenance Routine

A scheduled pg_cron routine runs weekly to pre-create upcoming monthly partitions and migrate partitions older than 180 days to warm object storage (S3/GCS parquet format via BigLake external foreign tables).
