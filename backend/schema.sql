CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS clients (
 id uuid PRIMARY KEY, name text NOT NULL UNIQUE, webhook_hash text NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS users (
 id uuid PRIMARY KEY, client_id uuid REFERENCES clients(id), email text NOT NULL UNIQUE,
 name text NOT NULL, password_hash text NOT NULL, role text NOT NULL CHECK(role IN ('Admin','Employee')),
 created_at timestamptz NOT NULL DEFAULT now(), CHECK(role = 'Admin' OR client_id IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, email text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS login_attempts_lookup ON login_attempts(email, created_at);
CREATE TABLE IF NOT EXISTS settings (
 id integer PRIMARY KEY CHECK(id = 1), notify_enabled boolean NOT NULL DEFAULT false,
 generation integer NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO settings(id) VALUES(1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS discoveries (
 id uuid PRIMARY KEY, client_id uuid NOT NULL REFERENCES clients(id), created_by uuid NOT NULL REFERENCES users(id),
 seed_ip inet NOT NULL, ssh_username text NOT NULL, ssh_password_encrypted text NOT NULL,
 max_depth integer NOT NULL CHECK(max_depth BETWEEN 0 AND 10),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed')),
 error text, created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 started_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_discovery ON discoveries(client_id) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS topologies (
 id uuid PRIMARY KEY, client_id uuid NOT NULL REFERENCES clients(id), discovery_id uuid NOT NULL UNIQUE REFERENCES discoveries(id),
 snapshot jsonb NOT NULL, vlans jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS original_logs (
 id uuid PRIMARY KEY, client_id uuid NOT NULL REFERENCES clients(id), payload jsonb NOT NULL,
 received_at timestamptz NOT NULL DEFAULT now(), event_key text,
 UNIQUE(client_id, event_key)
);
CREATE TABLE IF NOT EXISTS log_history (
 id uuid PRIMARY KEY, client_id uuid NOT NULL REFERENCES clients(id), original_id uuid NOT NULL REFERENCES original_logs(id),
 device text NOT NULL, message text NOT NULL, severity text NOT NULL DEFAULT 'unknown',
 occurred_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS log_history_search ON log_history(client_id, occurred_at DESC);
CREATE TABLE IF NOT EXISTS reports (
 id uuid PRIMARY KEY, client_id uuid NOT NULL REFERENCES clients(id), original_id uuid NOT NULL UNIQUE REFERENCES original_logs(id),
 device text NOT NULL, status text NOT NULL CHECK(status IN ('queued','running','completed','failed','suppressed')),
 generation integer NOT NULL, output text, model text, error text,
 notification_status text NOT NULL DEFAULT 'pending', created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz, finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS reports_client_date ON reports(client_id, created_at DESC);
CREATE TABLE IF NOT EXISTS audit_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, actor_id uuid REFERENCES users(id),
 action text NOT NULL, details jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;
ALTER TABLE discoveries ADD COLUMN IF NOT EXISTS progress jsonb;
ALTER TABLE discoveries ADD COLUMN IF NOT EXISTS progress_updated_at timestamptz;
INSERT INTO schema_migrations(version) VALUES(2) ON CONFLICT DO NOTHING;
ALTER TABLE discoveries DROP CONSTRAINT IF EXISTS discoveries_status_check;
ALTER TABLE discoveries ADD CONSTRAINT discoveries_status_check CHECK(status IN ('queued','running','cancelling','cancelled','completed','failed'));
DROP INDEX IF EXISTS one_active_discovery;
CREATE UNIQUE INDEX one_active_discovery ON discoveries(client_id) WHERE status IN ('queued','running','cancelling');
INSERT INTO schema_migrations(version) VALUES(3) ON CONFLICT DO NOTHING;

ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
INSERT INTO schema_migrations(version) VALUES(4) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS user_organizations (
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id, client_id)
);
CREATE INDEX IF NOT EXISTS user_organizations_client ON user_organizations(client_id);
INSERT INTO schema_migrations(version) VALUES(5) ON CONFLICT DO NOTHING;
ALTER TABLE discoveries ADD COLUMN IF NOT EXISTS ssh_credentials_encrypted text;
INSERT INTO schema_migrations(version) VALUES(6) ON CONFLICT DO NOTHING;

-- Credentials are transient job inputs, never retained in finished history.
ALTER TABLE discoveries ALTER COLUMN ssh_username DROP NOT NULL;
ALTER TABLE discoveries ALTER COLUMN ssh_password_encrypted DROP NOT NULL;
CREATE OR REPLACE FUNCTION erase_finished_discovery_credentials() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status IN ('completed', 'failed', 'cancelled') THEN
  NEW.ssh_username := NULL;
  NEW.ssh_password_encrypted := NULL;
  NEW.ssh_credentials_encrypted := NULL;
 END IF;
 RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER erase_finished_discovery_credentials
BEFORE INSERT OR UPDATE ON discoveries
FOR EACH ROW EXECUTE FUNCTION erase_finished_discovery_credentials();
UPDATE discoveries
SET ssh_username=NULL, ssh_password_encrypted=NULL, ssh_credentials_encrypted=NULL
WHERE status IN ('completed', 'failed', 'cancelled')
 AND (ssh_username IS NOT NULL OR ssh_password_encrypted IS NOT NULL OR ssh_credentials_encrypted IS NOT NULL);
INSERT INTO schema_migrations(version) VALUES(7) ON CONFLICT DO NOTHING;

-- Removed employees can retain historical references without a default organization.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_check;
ALTER TABLE users ADD CONSTRAINT users_check CHECK(role = 'Admin' OR client_id IS NOT NULL OR deleted_at IS NOT NULL);
INSERT INTO schema_migrations(version) VALUES(8) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS discovery_schedules (
 client_id uuid PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
 created_by uuid NOT NULL REFERENCES users(id), seed_ip inet NOT NULL,
 credentials_encrypted text NOT NULL, max_depth integer NOT NULL CHECK(max_depth BETWEEN 0 AND 10),
 repeat_days integer NOT NULL CHECK(repeat_days IN (1,7,30)), next_run_at timestamptz NOT NULL
);
ALTER TABLE discoveries ALTER COLUMN seed_ip DROP NOT NULL;
CREATE OR REPLACE FUNCTION erase_finished_discovery_credentials() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status IN ('completed', 'failed', 'cancelled') THEN
  NEW.seed_ip := NULL;
  NEW.ssh_username := NULL;
  NEW.ssh_password_encrypted := NULL;
  NEW.ssh_credentials_encrypted := NULL;
 END IF;
 RETURN NEW;
END;
$$;
INSERT INTO schema_migrations(version) VALUES(9) ON CONFLICT DO NOTHING;
