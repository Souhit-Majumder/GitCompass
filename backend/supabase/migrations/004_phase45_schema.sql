-- Phase 4.5 Schema Updates

-- Add commit_type to commits table
ALTER TABLE public.commits
ADD COLUMN IF NOT EXISTS commit_type text;

-- Create temporal_coupling table
CREATE TABLE IF NOT EXISTS public.temporal_coupling (
    id uuid NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    repo_id uuid NOT NULL REFERENCES public.repositories(id) ON DELETE CASCADE,
    file_a text NOT NULL,
    file_b text NOT NULL,
    co_changes integer NOT NULL DEFAULT 0,
    coupling_percentage numeric(5,2) NOT NULL DEFAULT 0.00,
    created_at timestamp with time zone DEFAULT now()
);

-- Index for querying couplings for a specific file (requested by user guardrails)
CREATE INDEX IF NOT EXISTS idx_temporal_coupling_file_a ON public.temporal_coupling(repo_id, file_a);
CREATE INDEX IF NOT EXISTS idx_temporal_coupling_file_b ON public.temporal_coupling(repo_id, file_b);

-- Enable RLS
ALTER TABLE public.temporal_coupling ENABLE ROW LEVEL SECURITY;

-- Service role bypass
CREATE POLICY "Service role has full access to temporal_coupling"
    ON public.temporal_coupling
    AS PERMISSIVE
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Authenticated users can read temporal_coupling for their repos
CREATE POLICY "Users can read temporal_coupling for their repos"
    ON public.temporal_coupling
    FOR SELECT
    TO authenticated
    USING (
        repo_id IN (
            SELECT id FROM public.repositories WHERE user_id = auth.uid()
        )
    );
