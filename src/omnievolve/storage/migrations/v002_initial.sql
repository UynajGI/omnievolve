-- v002: Add checkpoint_data column to experiment table
-- Stores volatile evolution state (meta_scratchpad, failed_directions, recent_scores)
-- for crash recovery.

ALTER TABLE experiment ADD COLUMN checkpoint_data TEXT;
