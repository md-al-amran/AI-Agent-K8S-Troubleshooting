-- InsForge schema for investigation history and realtime progress.
-- Run once (InsForge dashboard SQL editor, or the run-raw-sql MCP tool). Safe to re-run.

-- 1. History table: one row per investigation, updated as it progresses.
CREATE TABLE IF NOT EXISTS public.investigations (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
  status        text NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'success', 'partial', 'error')),
  cluster       text,                         -- kubeconfig context that was investigated
  current_step  text,                         -- step running now, e.g. 'logs'
  steps         text[] NOT NULL DEFAULT '{}', -- steps finished so far
  title         text,
  root_cause    text,
  namespace     text,
  severity      text,
  confidence    integer CHECK (confidence BETWEEN 0 AND 100),
  diagnosis     jsonb,                        -- full AI diagnosis, to reopen from history
  error         text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Added later; keeps older databases in sync.
ALTER TABLE public.investigations ADD COLUMN IF NOT EXISTS cluster text;

CREATE INDEX IF NOT EXISTS investigations_user_created_idx
  ON public.investigations (user_id, created_at DESC);

-- 2. Row Level Security: each user only sees and changes their own rows.
--    The FastAPI backend writes with the user's own access token, so these apply to it too.
ALTER TABLE public.investigations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own investigations: select" ON public.investigations;
CREATE POLICY "own investigations: select" ON public.investigations
  FOR SELECT TO authenticated USING (user_id = auth.uid());

DROP POLICY IF EXISTS "own investigations: insert" ON public.investigations;
CREATE POLICY "own investigations: insert" ON public.investigations
  FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "own investigations: update" ON public.investigations;
CREATE POLICY "own investigations: update" ON public.investigations
  FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

GRANT SELECT, INSERT, UPDATE ON public.investigations TO authenticated;

-- 3. Keep updated_at current.
CREATE OR REPLACE FUNCTION public.investigations_touch_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS investigations_touch_updated_at ON public.investigations;
CREATE TRIGGER investigations_touch_updated_at
  BEFORE UPDATE ON public.investigations
  FOR EACH ROW EXECUTE FUNCTION public.investigations_touch_updated_at();

-- 4. Realtime: every insert/update is pushed to the owner's channel
--    'investigations:<user_id>' as a 'progress' event.
CREATE OR REPLACE FUNCTION public.investigations_publish_progress()
RETURNS trigger AS $$
BEGIN
  PERFORM realtime.publish(
    'investigations:' || NEW.user_id::text,
    'progress',
    jsonb_build_object(
      'id', NEW.id,
      'status', NEW.status,
      'cluster', NEW.cluster,
      'current_step', NEW.current_step,
      'steps', to_jsonb(NEW.steps),
      'title', NEW.title,
      'root_cause', NEW.root_cause,
      'namespace', NEW.namespace,
      'confidence', NEW.confidence,
      'error', NEW.error,
      'created_at', NEW.created_at
    )
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS investigations_publish_progress ON public.investigations;
CREATE TRIGGER investigations_publish_progress
  AFTER INSERT OR UPDATE ON public.investigations
  FOR EACH ROW EXECUTE FUNCTION public.investigations_publish_progress();

-- 5. Realtime channel, readable only by its owner.
INSERT INTO realtime.channels (pattern, description, enabled)
SELECT 'investigations:%', 'Live progress of a user''s investigations', true
WHERE NOT EXISTS (SELECT 1 FROM realtime.channels WHERE pattern = 'investigations:%');

ALTER TABLE realtime.channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE realtime.messages ENABLE ROW LEVEL SECURITY;  -- no INSERT policy: clients cannot publish

DROP POLICY IF EXISTS "subscribe own investigations" ON realtime.channels;
CREATE POLICY "subscribe own investigations" ON realtime.channels
  FOR SELECT TO authenticated
  USING (
    pattern = 'investigations:%'
    AND realtime.channel_name() = 'investigations:' || auth.uid()::text
  );
