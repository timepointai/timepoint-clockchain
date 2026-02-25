-- Migration 001: Add source_type tracking columns
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'historical';
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS confidence FLOAT;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS source_run_id TEXT;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS tdf_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_nodes_source_type ON nodes(source_type);

-- Backfill: tag expander-created nodes
UPDATE nodes SET source_type = 'expander' WHERE created_by = 'expander';
-- Belt-and-suspenders: also catch expander nodes that have created_by='system'
UPDATE nodes SET source_type = 'expander' WHERE flash_timepoint_id IS NULL AND layer = 1 AND source_type = 'historical';
