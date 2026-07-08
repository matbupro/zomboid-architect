-- =============================================================================
-- 001_initial_schema.sql — Schema PostgreSQL complet du Pipeline de Production PZ
-- =============================================================================
-- Projet: Zomboid Knowledge Engine — Agent Autonome de Production de Mods PZ
-- Version: 1.0.0
-- Date: 2026-07-07
-- Reference: Section C de agent-autonome-mods-pz.md + additions tasks.md S2-iii
--
-- Ce fichier contient TOUT le schema initial du pipeline:
--   - 12 tables principales (mod_projects, agent_runs, mod_artifacts, ...)
--   - 7 types ENUM
--   - 3 vues utiles (v_latest_validated_artifact, v_run_success_rate, v_validation_trends)
--   - 2 triggers de maintenance + 1 trigger de stats
--   - 4 tables additionnelles pour l'ingestion PZ (ingestion_runs, data_coverage, collection_health, data_links)

-- Extensions nécessaires
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";


-- =============================================================================
-- Types ENUM
-- =============================================================================

CREATE TYPE agent_status AS ENUM (
    'pending', 'planning', 'building', 'validating_l1',
    'validating_l2', 'validating_l3', 'validating_l4',
    'fixing', 'packaging', 'done', 'failed', 'escalated', 'cancelled'
);

CREATE TYPE validation_level AS ENUM (
    'l1_static', 'l2_boot', 'l3_runtime', 'l4_functional'
);

CREATE TYPE validation_result AS ENUM (
    'passed', 'failed', 'warning', 'error', 'skipped'
);

CREATE TYPE governance_tier AS ENUM ('green', 'orange', 'red');
CREATE TYPE build_target AS ENUM ('build41', 'build42', 'both');
CREATE TYPE publish_status AS ENUM ('draft', 'review', 'approved', 'published', 'deprecated');
CREATE TYPE dependency_type AS ENUM ('requires', 'recommends', 'suggests', 'conflicts', 'provides');


-- =============================================================================
-- Tables principales (section C du doc)
-- =============================================================================

-- mod_projects — un projet = un mod PZ a produire
CREATE TABLE mod_projects (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mod_id          VARCHAR(128) NOT NULL UNIQUE,
    name            VARCHAR(256) NOT NULL,
    description     TEXT,
    author          VARCHAR(128) DEFAULT 'AgentAI',
    version         VARCHAR(32) DEFAULT '1.0.0',
    build_target    build_target DEFAULT 'build42',
    publish_status  publish_status DEFAULT 'draft',
    poster_url      VARCHAR(512),
    workshop_id     BIGINT,
    git_repo        VARCHAR(256),
    total_runs      INTEGER DEFAULT 0,
    success_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    last_run_at     TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}',
    CONSTRAINT mod_id_format CHECK (mod_id ~ '^[A-Za-z0-9_.-]+$')
);

CREATE INDEX idx_mod_projects_status ON mod_projects(publish_status);
CREATE INDEX idx_mod_projects_git_repo ON mod_projects(git_repo) WHERE git_repo IS NOT NULL;
CREATE INDEX idx_mod_projects_search ON mod_projects USING gin(name gin_trgm_ops);

-- agent_runs — chaque execution de la boucle agentique
CREATE TABLE agent_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES mod_projects(id) ON DELETE SET NULL,
    run_number      SERIAL,
    run_label       VARCHAR(128),
    status          agent_status DEFAULT 'pending',
    governance_tier governance_tier DEFAULT 'green',
    plan            JSONB DEFAULT '{}',
    build_target    build_target DEFAULT 'build42',
    user_request    TEXT NOT NULL,
    context_chunks  JSONB DEFAULT '[]',
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 5,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    errors          JSONB DEFAULT '[]',
    error_summary   TEXT,
    artifact_id     UUID REFERENCES mod_artifacts(id) ON DELETE SET NULL,
    assigned_to     VARCHAR(128),
    CONSTRAINT unique_run_per_project UNIQUE (project_id, run_number)
);

CREATE INDEX idx_agent_runs_project ON agent_runs(project_id);
CREATE INDEX idx_agent_runs_status ON agent_runs(status);
CREATE INDEX idx_agent_runs_started ON agent_runs(started_at DESC);
CREATE INDEX idx_agent_runs_tier ON agent_runs(governance_tier);

-- mod_artifacts — le zip final d'un mod valide
CREATE TABLE mod_artifacts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    version         VARCHAR(32) NOT NULL,
    checksum        VARCHAR(64),
    file_count      INTEGER DEFAULT 0,
    total_size_bytes BIGINT DEFAULT 0,
    minio_path      VARCHAR(512),
    minio_url       VARCHAR(1024),
    commit_sha      VARCHAR(40),
    git_branch      VARCHAR(128),
    validation_summary JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT unique_artifact_per_run_version UNIQUE (run_id, version)
);

CREATE INDEX idx_mod_artifacts_run ON mod_artifacts(run_id);
CREATE INDEX idx_mod_artifacts_minio ON mod_artifacts(minio_path) WHERE minio_path IS NOT NULL;
CREATE INDEX idx_mod_artifacts_git ON mod_artifacts(commit_sha) WHERE commit_sha IS NOT NULL;

-- mod_files — chaque fichier d'un artifact de mod
CREATE TABLE mod_files (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    artifact_id     UUID REFERENCES mod_artifacts(id) ON DELETE CASCADE,
    file_path       VARCHAR(512) NOT NULL,
    file_type       VARCHAR(32),
    file_role       VARCHAR(32),
    content_hash    VARCHAR(64),
    size_bytes      INTEGER,
    luacheck_score  INTEGER,
    luacheck_warnings INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT unique_file_per_artifact_path UNIQUE (artifact_id, file_path)
);

CREATE INDEX idx_mod_files_artifact ON mod_files(artifact_id);
CREATE INDEX idx_mod_files_type ON mod_files(file_type);
CREATE INDEX idx_mod_files_role ON mod_files(file_role);

-- mod_dependencies — dependances entre mods
CREATE TABLE mod_dependencies (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES mod_projects(id) ON DELETE CASCADE,
    dependent_id    UUID REFERENCES mod_projects(id) ON DELETE CASCADE,
    dependency_type dependency_type DEFAULT 'requires',
    version_min     VARCHAR(32),
    version_max     VARCHAR(32),
    external_mod_id VARCHAR(128),
    external_url    VARCHAR(512),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT no_self_dependency CHECK (project_id != dependent_id)
);

CREATE INDEX idx_mod_deps_project ON mod_dependencies(project_id);
CREATE INDEX idx_mod_deps_dependent ON mod_dependencies(dependent_id);

-- knowledge_chunks — le corpus de connaissances PZ (tout format confondu)
CREATE TABLE knowledge_chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES mod_projects(id) ON DELETE CASCADE,
    category        VARCHAR(64) NOT NULL,
    subcategory     VARCHAR(128),
    content_text    TEXT NOT NULL,
    content_hash    VARCHAR(64) NOT NULL,
    source_url      VARCHAR(512),
    source_type     VARCHAR(32),
    source_date     DATE,
    source_title    VARCHAR(256),
    qdrant_point_id VARCHAR(128),
    qdrant_vector_id BIGINT,
    chunk_index     INTEGER,
    token_count     INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ,
    tags            JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX idx_knowledge_chunks_project ON knowledge_chunks(project_id);
CREATE INDEX idx_knowledge_chunks_category ON knowledge_chunks(category);
CREATE INDEX idx_knowledge_chunks_qdrant ON knowledge_chunks(qdrant_point_id) WHERE qdrant_point_id IS NOT NULL;
CREATE INDEX idx_knowledge_chunks_search ON knowledge_chunks USING gin(content_text gin_trgm_ops);
CREATE INDEX idx_knowledge_chunks_source ON knowledge_chunks(source_type, source_date);

-- api_reference — reference API Lua + Java de PZ
CREATE TABLE api_reference (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    element_name    VARCHAR(256) NOT NULL,
    element_type    VARCHAR(64) NOT NULL,
    build_target    build_target DEFAULT 'both',
    deprecated_in   VARCHAR(32),
    removed_in      VARCHAR(32),
    description     TEXT,
    syntax          TEXT,
    parameters      JSONB DEFAULT '[]',
    return_value    TEXT,
    example_code    TEXT,
    common_errors   JSONB DEFAULT '[]',
    source          VARCHAR(256),
    wiki_url        VARCHAR(512),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_api_reference_type ON api_reference(element_type);
CREATE INDEX idx_api_reference_name ON api_reference(element_name) UNIQUE;
CREATE INDEX idx_api_reference_build ON api_reference(build_target);

-- test_scenarios — scenarios de test pour validation des mods
CREATE TABLE test_scenarios (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES mod_projects(id) ON DELETE CASCADE,
    scenario_name   VARCHAR(256) NOT NULL,
    description     TEXT,
    test_type       VARCHAR(64),
    validation_level validation_level,
    test_script     TEXT NOT NULL,
    expected_outcome TEXT,
    success_criteria JSONB DEFAULT '{}',
    last_run_at     TIMESTAMPTZ,
    last_result     validation_result,
    last_error      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_test_scenarios_project ON test_scenarios(project_id);
CREATE INDEX idx_test_scenarios_type ON test_scenarios(test_type);

-- fix_attempts — chaque tentative de correction d'un bug de mod
CREATE TABLE fix_attempts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    fix_number      INTEGER NOT NULL,
    validation_level validation_level,
    error_type      VARCHAR(128),
    error_message   TEXT,
    fix_description TEXT,
    files_modified  JSONB DEFAULT '[]',
    resolved        BOOLEAN DEFAULT FALSE,
    new_errors      JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fix_attempts_run ON fix_attempts(run_id);

-- validation_results — resultats de chaque niveau de validation
CREATE TABLE validation_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    artifact_id     UUID REFERENCES mod_artifacts(id) ON DELETE CASCADE,
    validation_level validation_level NOT NULL,
    result          validation_result NOT NULL,
    duration_ms     INTEGER,
    files_checked   INTEGER DEFAULT 0,
    errors_found    INTEGER DEFAULT 0,
    warnings_found  INTEGER DEFAULT 0,
    output_log      TEXT,
    error_details   JSONB DEFAULT '[]',
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ
);

CREATE INDEX idx_validation_results_run ON validation_results(run_id);
CREATE INDEX idx_validation_results_level ON validation_results(validation_level);
CREATE INDEX idx_validation_results_result ON validation_results(result);

-- publish_log — historique de publication des mods
CREATE TABLE publish_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES mod_projects(id) ON DELETE CASCADE,
    artifact_id     UUID REFERENCES mod_artifacts(id) ON DELETE SET NULL,
    publish_type    VARCHAR(32),
    status          VARCHAR(32) DEFAULT 'pending',
    error_message   TEXT,
    publish_url     VARCHAR(1024),
    validation_passed BOOLEAN,
    human_approved   BOOLEAN,
    approved_by     VARCHAR(128),
    requested_at    TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_publish_log_project ON publish_log(project_id);
CREATE INDEX idx_publish_log_status ON publish_log(status);

-- users — gestion des utilisateurs du systeme (si multi-owners)
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(128) NOT NULL UNIQUE,
    email           VARCHAR(256) NOT NULL UNIQUE,
    role            VARCHAR(32) DEFAULT 'developer',
    can_publish_steam  BOOLEAN DEFAULT FALSE,
    can_merge_main     BOOLEAN DEFAULT FALSE,
    can_escalate       BOOLEAN DEFAULT FALSE,
    can_view_secrets   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ,
    CONSTRAINT valid_role CHECK (role IN ('admin', 'developer', 'reviewer', 'viewer'))
);

CREATE INDEX idx_users_role ON users(role);


-- =============================================================================
-- Vues utiles (section C du doc)
-- =============================================================================

CREATE OR REPLACE VIEW v_latest_validated_artifact AS
SELECT DISTINCT ON (p.id)
    p.id AS project_id, p.mod_id, p.name,
    ma.id AS artifact_id, ma.version, ma.created_at,
    ma.validation_summary, ar.status AS run_status
FROM mod_artifacts ma
JOIN agent_runs ar ON ma.run_id = ar.id
JOIN mod_projects p ON ar.project_id = p.id
WHERE ar.status = 'done'
ORDER BY p.id, ma.created_at DESC;

CREATE VIEW v_run_success_rate AS
SELECT
    p.mod_id, p.name,
    COUNT(ar.id) AS total_runs,
    COUNT(CASE WHEN ar.status = 'done' THEN 1 END) AS successful_runs,
    COUNT(CASE WHEN ar.status = 'failed' THEN 1 END) AS failed_runs,
    ROUND(
        COUNT(CASE WHEN ar.status = 'done' THEN 1 END)::NUMERIC /
        NULLIF(COUNT(ar.id), 0) * 100, 2
    ) AS success_rate_pct,
    AVG(EXTRACT(EPOCH FROM ar.ended_at - ar.started_at)) AS avg_duration_seconds
FROM mod_projects p
LEFT JOIN agent_runs ar ON p.id = ar.project_id
    AND ar.started_at > NOW() - INTERVAL '30 days'
GROUP BY p.id, p.mod_id, p.name;

CREATE VIEW v_validation_trends AS
SELECT
    DATE(started_at) AS date,
    validation_level,
    COUNT(*) AS total_runs,
    COUNT(CASE WHEN result = 'passed' THEN 1 END) AS passed,
    COUNT(CASE WHEN result = 'failed' THEN 1 END) AS failed,
    ROUND(
        COUNT(CASE WHEN result = 'passed' THEN 1 END)::NUMERIC /
        NULLIF(COUNT(*), 0) * 100, 2
    ) AS pass_rate_pct
FROM validation_results
WHERE started_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(started_at), validation_level
ORDER BY date DESC, validation_level;


-- =============================================================================
-- Triggers de maintenance (section C du doc)
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_mod_projects_updated
    BEFORE UPDATE ON mod_projects FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_api_reference_updated
    BEFORE UPDATE ON api_reference FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Trigger de mise a jour des stats de projet lors d'une execution terminee
CREATE OR REPLACE FUNCTION update_project_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'done' THEN
        UPDATE mod_projects SET total_runs = total_runs + 1,
            success_count = success_count + 1, last_run_at = NOW()
        WHERE id = (SELECT project_id FROM agent_runs WHERE id = NEW.id);
    ELSIF NEW.status IN ('failed', 'escalated') THEN
        UPDATE mod_projects SET total_runs = total_runs + 1, last_run_at = NOW()
        WHERE id = (SELECT project_id FROM agent_runs WHERE id = NEW.id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_run_completion_stats
    AFTER UPDATE ON agent_runs FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION update_project_stats();


-- =============================================================================
-- Tables additionnelles pour l'ingestion PZ (tasks.md S2-iii)
-- =============================================================================

-- ingestion_runs — suivre chaque cycle d'ingestion PZ
CREATE TABLE ingestion_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type     VARCHAR(32) NOT NULL,       -- wikidrive, wikiweb, workshop, classz, moddinguide
    source_url      VARCHAR(512),
    source_file     VARCHAR(512),               -- chemin local si fichier
    status          VARCHAR(16) DEFAULT 'running' CHECK (status IN ('pending','running','done','failed','partial')),
    chunks_generated INTEGER DEFAULT 0,
    chunks_failed   INTEGER DEFAULT 0,
    errors          JSONB DEFAULT '[]',
    duration_ms     INTEGER,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}'            -- details specifiques a la source
);

CREATE INDEX idx_ingestion_runs_status ON ingestion_runs(status);
CREATE INDEX idx_ingestion_runs_source ON ingestion_runs(source_type);
CREATE INDEX idx_ingestion_runs_started ON ingestion_runs(started_at DESC);


-- data_coverage — tracking % coverage par category vs total connu
CREATE TABLE data_coverage (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category        VARCHAR(64) NOT NULL,
    item_name       VARCHAR(256) NOT NULL,
    is_documented   BOOLEAN DEFAULT FALSE,
    data_completeness_score FLOAT DEFAULT 0.0,  -- 0-1: % fields remplis
    last_ingested_at TIMESTAMPTZ,
    ingestion_run_id UUID REFERENCES ingestion_runs(id),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_coverage_category ON data_coverage(category);
CREATE INDEX idx_coverage_documented ON data_coverage(is_documented) WHERE is_documented = FALSE;


-- collection_health — monitoring par collection PG/Qdrant
CREATE TABLE collection_health (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    collection_name VARCHAR(64) NOT NULL UNIQUE,
    chunk_count     INTEGER DEFAULT 0,
    vector_dim      INTEGER,
    last_ingested_at TIMESTAMPTZ,
    is_healthy      BOOLEAN DEFAULT TRUE,
    error_detail    TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);


-- data_links — graph de connaissances croisees (items ↔ recipes ↔ mobs)
CREATE TABLE data_links (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_category VARCHAR(64) NOT NULL,        -- items, recipes, mobs, skills, ...
    source_name     VARCHAR(256) NOT NULL,       -- nom de l'entite source
    target_category VARCHAR(64) NOT NULL,        -- category cible
    target_name     VARCHAR(256) NOT NULL,       -- nom de l'entite cible
    link_type       VARCHAR(64) NOT NULL,        -- ingredient_of, drop_by, unlocks, counter_to, ...
    confidence      FLOAT DEFAULT 1.0,           -- 1.0 = confirmee manuellement
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_data_links_source ON data_links(source_category, source_name);
CREATE INDEX idx_data_links_target ON data_links(target_category, target_name);
CREATE INDEX idx_data_links_type ON data_links(link_type);


-- =============================================================================
-- Trigger auto-update pour updated_at sur les nouvelles tables
-- =============================================================================

CREATE TRIGGER trg_coverage_updated
    BEFORE UPDATE ON data_coverage FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_collection_updated
    BEFORE UPDATE ON collection_health FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- =============================================================================
-- Vue: data_coverage_summary — % coverage global et par category
-- =============================================================================

CREATE OR REPLACE VIEW v_coverage_summary AS
SELECT
    category,
    COUNT(*) AS total_items,
    SUM(CASE WHEN is_documented THEN 1 ELSE 0 END) AS documented,
    ROUND((AVG(data_completeness_score) * 100)::numeric, 2) AS avg_completeness_pct,
    ROUND(
        SUM(CASE WHEN is_documented THEN 1 ELSE 0 END)::NUMERIC /
        NULLIF(COUNT(*), 0) * 100, 2
    ) AS coverage_pct
FROM data_coverage
GROUP BY category
ORDER BY coverage_pct ASC;

-- =============================================================================
-- Vue: ingestion_health — etat actuel de l'ingestion
-- =============================================================================

CREATE OR REPLACE VIEW v_ingestion_health AS
SELECT
    source_type,
    status,
    COUNT(*) AS run_count,
    AVG(duration_ms) AS avg_duration_ms,
    SUM(chunks_generated) AS total_chunks,
    SUM(chunks_failed) AS total_failures
FROM ingestion_runs
WHERE started_at > NOW() - INTERVAL '7 days'
GROUP BY source_type, status
ORDER BY source_type, status;
