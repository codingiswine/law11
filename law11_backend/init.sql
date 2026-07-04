-- ========================================
-- Law11 Database Initialization Script
-- ========================================
-- This script is automatically executed when PostgreSQL container starts

-- Create extension for UUID support
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────
-- 💬 Chat History Table
-- ─────────────────────────────
CREATE TABLE IF NOT EXISTS chat_history (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    turn_index BIGINT NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    metadata JSONB DEFAULT '{}',
    score INTEGER DEFAULT 0,
    feedback SMALLINT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_chat_history_user_id ON chat_history(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_session_id ON chat_history(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_created_at ON chat_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_history_metadata ON chat_history USING GIN(metadata);

-- ─────────────────────────────
-- ⚖️ Law Chunks Table
-- ─────────────────────────────
CREATE TABLE IF NOT EXISTS law_chunks (
    id SERIAL PRIMARY KEY,
    chunk_id VARCHAR(100) UNIQUE NOT NULL,
    law_name VARCHAR(255) NOT NULL,
    law_name_norm VARCHAR(255) NOT NULL,
    article_number VARCHAR(50),
    article_number_norm VARCHAR(50),
    paragraph_number VARCHAR(50),
    sub_paragraph_number VARCHAR(50),
    text TEXT NOT NULL,
    enforcement_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for law search
CREATE INDEX IF NOT EXISTS idx_law_chunks_law_name_norm ON law_chunks(law_name_norm);
CREATE INDEX IF NOT EXISTS idx_law_chunks_article_number_norm ON law_chunks(article_number_norm);
CREATE INDEX IF NOT EXISTS idx_law_chunks_composite ON law_chunks(law_name_norm, article_number_norm);
CREATE INDEX IF NOT EXISTS idx_law_chunks_enforcement_date ON law_chunks(enforcement_date DESC);

-- ─────────────────────────────
-- 🔄 Auto-update trigger for updated_at
-- ─────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_chat_history_updated_at BEFORE UPDATE ON chat_history
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_law_chunks_updated_at BEFORE UPDATE ON law_chunks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ─────────────────────────────
-- 📊 View for statistics
-- ─────────────────────────────
CREATE OR REPLACE VIEW chat_statistics AS
SELECT
    metadata->>'tool' as tool_name,
    COUNT(*) as usage_count,
    AVG(score) as avg_score,
    MAX(created_at) as last_used,
    COUNT(DISTINCT user_id) as unique_users
FROM chat_history
WHERE role = 'assistant'
GROUP BY metadata->>'tool';

-- ─────────────────────────────
-- 📌 Citations Table
-- ─────────────────────────────
CREATE TABLE IF NOT EXISTS citations (
    id SERIAL PRIMARY KEY,
    chat_history_id INTEGER REFERENCES chat_history(id) ON DELETE CASCADE,
    law_name VARCHAR(255) NOT NULL,
    article_number VARCHAR(50),
    score FLOAT,
    rank INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_citations_chat_history_id ON citations(chat_history_id);
CREATE INDEX IF NOT EXISTS idx_citations_law_name ON citations(law_name);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO daniel;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO daniel;
